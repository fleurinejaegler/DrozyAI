#import "RelayCoordinator.h"
#import "RelayProtocol.h"

@interface RelayCoordinator ()
@property(nonatomic, strong, readwrite) DrowsyWatchLink *watch;
@property(nonatomic, strong) NSTimer *timer;
@property(nonatomic) BOOL running;
@property(nonatomic) NSTimeInterval lastHeartbeat;
@property(nonatomic) NSTimeInterval lastModelSend;
@property(nonatomic, strong) NSDictionary *pendingModel;
@property(nonatomic, strong) NSDictionary *pendingCamera;
@property(nonatomic, strong) NSMutableDictionary<NSNumber *, NSDictionary *> *inFlight;
@property(nonatomic, strong) NSMutableArray<NSString *> *seenCommands;
@property(nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *inputTimes;
@property(nonatomic, strong) NSDictionary *lastTelemetry;
@property(nonatomic) NSTimeInterval lastTelemetryReceived;
@end

@implementation RelayCoordinator
- (instancetype)init {
    if ((self = [super init])) {
        self.inFlight = [NSMutableDictionary dictionary]; self.seenCommands = [NSMutableArray array]; self.inputTimes = [NSMutableDictionary dictionary];
        self.watch = [[DrowsyWatchLink alloc] initWithURLScheme:@"drowsyrelay-ciq"];
        __weak typeof(self) weakSelf = self;
        self.watch.onStatus = ^(NSString *status) {
            typeof(self) owner = weakSelf; if (!owner) return;
            if (owner.onStatus) owner.onStatus(status);
            [owner publishState];
        };
        self.watch.onTelemetry = ^(NSDictionary *packet) {
            typeof(self) owner = weakSelf; if (!owner || !owner.running) return;
            if (![owner.lastTelemetry[@"session"] isEqual:packet[@"session"]]) [owner.inputTimes removeAllObjects];
            owner.lastTelemetry = packet; owner.lastTelemetryReceived = NSDate.date.timeIntervalSince1970;
            owner.inputTimes[packet[@"sequence"]] = packet[@"sentAt"];
            for (NSNumber *key in owner.inputTimes.allKeys) {
                if (owner.lastTelemetryReceived - owner.inputTimes[key].doubleValue > 10) [owner.inputTimes removeObjectForKey:key];
            }
            [owner emit:@{@"protocol": @1, @"type": @"telemetry", @"receivedAt": @(owner.lastTelemetryReceived), @"payload": packet}];
        };
        self.watch.onWatchMessage = ^(NSDictionary *packet) { [weakSelf receivedWatchMessage:packet]; };
        self.watch.onTransportResult = ^(NSNumber *seq, BOOL success) {
            typeof(self) owner = weakSelf; NSDictionary *entry = owner.inFlight[seq];
            if (!entry) return;
            if (!success) {
                [owner result:entry[@"command"] status:@"transport_failed" sequence:seq];
                [owner.inFlight removeObjectForKey:seq];
            }
            // Success is only Bluetooth completion; acceptance requires a watch receipt.
        };
    }
    return self;
}
- (void)emit:(NSDictionary *)event { if (self.onEvent) self.onEvent(event); }
- (void)result:(NSDictionary *)command status:(NSString *)status sequence:(NSNumber *)seq {
    [self emit:@{@"protocol": @1, @"type": @"command_result", @"commandId": command[@"commandId"] ?: NSNull.null,
        @"status": status, @"watchSequence": seq ?: NSNull.null}];
    if ([command[@"type"] isEqual:@"model_result"] && ![status isEqual:@"queued"] && ![status isEqual:@"submitted"]) {
        [self emit:@{@"protocol": @1, @"type": @"model_result", @"payload": command,
            @"accepted": @([status isEqual:@"accepted"]), @"deliveryStatus": status}];
    }
}
- (void)start {
    if (self.running) return;
    self.running = YES;
    self.timer = [NSTimer scheduledTimerWithTimeInterval:0.25 target:self selector:@selector(tick) userInfo:nil repeats:YES];
    [self publishState];
}
- (void)pause {
    self.running = NO; [self.timer invalidate]; self.timer = nil;
    if (self.pendingModel) [self result:self.pendingModel status:@"paused" sequence:nil];
    if (self.pendingCamera) [self result:self.pendingCamera status:@"paused" sequence:nil];
    self.pendingModel = nil; self.pendingCamera = nil;
    for (NSNumber *seq in self.inFlight.allKeys) [self result:self.inFlight[seq][@"command"] status:@"delivery_unknown" sequence:seq];
    [self.inFlight removeAllObjects]; [self publishState];
}
- (void)selectWatch { [self.watch selectWatch]; }
- (NSArray<IQDevice *> *)devicesFromURL:(NSURL *)url { return [self.watch devicesFromURL:url]; }
- (void)attach:(IQDevice *)device {
    [self pause]; [self.inputTimes removeAllObjects]; self.lastTelemetry = nil;
    self.lastModelSend = 0; self.lastHeartbeat = 0;
    [self.watch attachDevice:device]; [self start];
}
- (void)publishState {
    [self emit:@{@"protocol": @1, @"type": @"state", @"running": @(self.running),
        @"watchSession": self.watch.watchSession ?: NSNull.null,
        @"telemetryRecent": @(self.lastTelemetry != nil && NSDate.date.timeIntervalSince1970-self.lastTelemetryReceived <= 10),
        @"modelIntervalSeconds": @5}];
}
- (void)receivedWatchMessage:(NSDictionary *)packet {
    [self emit:@{@"protocol": @1, @"type": @"watch_message", @"payload": packet}];
    if ([packet[@"type"] isEqual:@"receipt"]) {
        NSNumber *seq = packet[@"sequence"];
        NSDictionary *entry = [seq isKindOfClass:NSNumber.class] ? self.inFlight[seq] : nil;
        if (entry) {
            [self result:entry[@"command"] status:packet[@"status"] sequence:seq];
            [self.inFlight removeObjectForKey:seq];
        }
    }
    [self publishState];
}
- (void)receiveWebsiteCommand:(id)value {
    if (![value isKindOfClass:NSDictionary.class]) { [self result:@{} status:@"invalid_message" sequence:nil]; return; }
    NSDictionary *command = value;
    if (!self.running) { [self result:command status:@"paused" sequence:nil]; return; }
    NSString *error = [RelayProtocol validate:command watchSession:self.watch.watchSession now:NSDate.date.timeIntervalSince1970];
    if (error) { [self result:command status:error sequence:nil]; return; }
    if ([self.seenCommands containsObject:command[@"commandId"]]) { [self result:command status:@"duplicate" sequence:nil]; return; }
    if ([command[@"type"] isEqual:@"model_result"]) {
        NSNumber *input = self.inputTimes[command[@"inputTelemetrySequence"]];
        if (!input || NSDate.date.timeIntervalSince1970 - input.doubleValue > 10 ||
            [command[@"capturedAt"] doubleValue] < input.doubleValue - 2) {
            [self result:command status:@"unknown_or_stale_input" sequence:nil]; return;
        }
        if (self.pendingModel) [self result:self.pendingModel status:@"superseded" sequence:nil];
        self.pendingModel = command;
    } else {
        if (self.pendingCamera) [self result:self.pendingCamera status:@"superseded" sequence:nil];
        self.pendingCamera = command;
    }
    [self.seenCommands addObject:command[@"commandId"]];
    if (self.seenCommands.count > 128) [self.seenCommands removeObjectAtIndex:0];
    [self result:command status:@"queued" sequence:nil]; [self tick];
}
- (void)tick {
    if (!self.running) return;
    NSTimeInterval now = NSDate.date.timeIntervalSince1970;
    for (NSNumber *seq in self.inFlight.allKeys) {
        if (now - [self.inFlight[seq][@"sentAt"] doubleValue] > 10) {
            [self result:self.inFlight[seq][@"command"] status:@"receipt_timeout" sequence:seq];
            [self.inFlight removeObjectForKey:seq];
        }
    }
    if (self.pendingCamera && now - [self.pendingCamera[@"capturedAt"] doubleValue] > 10) {
        [self result:self.pendingCamera status:@"stale" sequence:nil]; self.pendingCamera = nil;
    }
    if (self.pendingModel && now - [self.pendingModel[@"capturedAt"] doubleValue] > 10) {
        [self result:self.pendingModel status:@"stale" sequence:nil]; self.pendingModel = nil;
    }
    // Keep at most one application command awaiting acknowledgment; camera has priority.
    NSDictionary *command = self.pendingCamera ?: (now-self.lastModelSend >= 5 ? self.pendingModel : nil);
    if (command && (self.pendingCamera != nil || self.inFlight.count == 0) && self.inFlight.count < 8 && self.watch.watchReady) {
        NSString *error = [RelayProtocol validate:command watchSession:self.watch.watchSession now:now];
        if (!error && [command[@"type"] isEqual:@"model_result"]) {
            NSNumber *input = self.inputTimes[command[@"inputTelemetrySequence"]];
            if (!input || now-input.doubleValue > 10) error = @"unknown_or_stale_input";
        }
        if (error) { [self result:command status:error sequence:nil]; }
        else {
            NSNumber *seq = [self.watch submitRelayCommand:command];
            if (seq) {
                self.inFlight[seq] = @{@"command": command, @"sentAt": @(now)};
                [self result:command status:@"submitted" sequence:seq];
                if ([command[@"type"] isEqual:@"model_result"]) self.lastModelSend = now;
            } else return;
        }
        if ([command[@"type"] isEqual:@"model_result"]) self.pendingModel = nil; else self.pendingCamera = nil;
    }
    if (now-self.lastHeartbeat >= 5) { self.lastHeartbeat = now; [self.watch heartbeat]; [self publishState]; }
}
- (void)dealloc { [self.timer invalidate]; [self.watch stop]; }
@end
