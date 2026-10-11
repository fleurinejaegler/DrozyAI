#import "DrowsyWatchLink.h"
#include <limits.h>
#include <math.h>

@interface DrowsyWatchLink ()
@property(nonatomic, strong) IQDevice *device;
@property(nonatomic, strong) IQApp *app;
@property(nonatomic, copy) NSString *session;
@property(nonatomic) BOOL ready;
@property(nonatomic) BOOL sending;
@property(nonatomic) NSInteger generation;
@property(nonatomic) NSInteger lastTelemetrySequence;
@end
@implementation DrowsyWatchLink
- (instancetype)initWithURLScheme:(NSString *)scheme {
    if ((self = [super init])) {
        [[ConnectIQ sharedInstance] initializeWithUrlScheme:scheme uiOverrideDelegate:nil];
    }
    return self;
}
- (void)status:(NSString *)value { if (self.onStatus) self.onStatus(value); }
- (void)selectWatch { [[ConnectIQ sharedInstance] showConnectIQDeviceSelection]; }
- (NSArray<IQDevice *> *)devicesFromURL:(NSURL *)url {
    return [[ConnectIQ sharedInstance] parseDeviceSelectionResponseFromURL:url];
}
- (void)attachDevice:(IQDevice *)device {
    [self stop];
    self.device = device;
    self.app = [IQApp appWithUUID:[[NSUUID alloc] initWithUUIDString:@"5222d277-26f2-4f31-8df5-77bfe31c4598"] device:device];
    [[ConnectIQ sharedInstance] registerForDeviceEvents:device delegate:self];
    [[ConnectIQ sharedInstance] registerForAppMessages:self.app delegate:self];
    [self status:@"Connecting to watch"];
}
- (void)deviceStatusChanged:(IQDevice *)device status:(IQDeviceStatus)status {
    if (![device.uuid isEqual:self.device.uuid]) return;
    if (status != IQDeviceStatus_Connected) {
        self.ready = NO; self.session = nil; self.sending = NO; self.generation++;
        [self status:@"Watch disconnected; alert delivery unavailable"];
    }
    // Connected alone is insufficient: wait for characteristics discovery.
}
- (void)deviceCharacteristicsDiscovered:(IQDevice *)device {
    if (![device.uuid isEqual:self.device.uuid]) return;
    self.ready = YES;
    [self heartbeat];
}
- (BOOL)sendType:(NSString *)type severity:(NSString *)severity capturedAt:(NSDate *)captureTime {
    NSAssert([NSThread isMainThread], @"Use DrowsyWatchLink on main thread");
    if (!self.ready || !self.app || self.sending) {
        [self status:@"Watch unavailable or send busy; message not sent"]; return NO;
    }
    NSTimeInterval age = -[captureTime timeIntervalSinceNow];
    if (age > 10 || age < -2) { [self status:@"Old/future model result rejected"]; return NO; }
    if (![type isEqualToString:@"hello"] && !self.session) {
        [self status:@"Watch handshake incomplete; alert not sent"]; return NO;
    }
    NSMutableDictionary *message = [@{@"protocol": @1, @"source": @"phone_video",
        @"type": type, @"sentAt": @((int32_t)floor(captureTime.timeIntervalSince1970))} mutableCopy];
    if (self.session) {
        NSInteger sequence = [[NSUserDefaults standardUserDefaults] integerForKey:@"DrowsyAlertSequence"];
        if (sequence >= INT32_MAX) { [self status:@"Sequence exhausted; reset integration required"]; return NO; }
        sequence++;
        [[NSUserDefaults standardUserDefaults] setInteger:sequence forKey:@"DrowsyAlertSequence"];
        message[@"session"] = self.session; message[@"sequence"] = @((int32_t)sequence);
    }
    if (severity) message[@"severity"] = severity;
    self.sending = YES;
    NSInteger generation = self.generation;
    __weak typeof(self) weakSelf = self;
    [[ConnectIQ sharedInstance] sendMessage:message toApp:self.app progress:^(uint32_t sent, uint32_t total) {}
        completion:^(IQSendMessageResult result) {
            dispatch_async(dispatch_get_main_queue(), ^{
                typeof(self) owner = weakSelf;
                if (!owner || owner.generation != generation) return;
                owner.sending = NO;
                // Transport completion is NOT confirmation that watch accepted an alert.
                [owner status:[NSString stringWithFormat:@"Bluetooth send: %@; check watch receipt", NSStringFromSendMessageResult(result)]];
            });
        } isTransient:YES];
    return YES;
}
- (BOOL)sendDrowsinessSeverity:(NSString *)severity capturedAt:(NSDate *)captureTime {
    if (![severity isEqualToString:@"warning"] && ![severity isEqualToString:@"high"]) return NO;
    return [self sendType:@"alert" severity:severity capturedAt:captureTime];
}
- (BOOL)clearPhoneAlertCapturedAt:(NSDate *)captureTime {
    return [self sendType:@"clear" severity:nil capturedAt:captureTime];
}
- (void)heartbeat {
    [self sendType:self.session ? @"heartbeat" : @"hello" severity:nil capturedAt:[NSDate date]];
}
- (NSString *)watchSession { return self.session; }
- (BOOL)watchReady { return self.ready && self.session != nil && !self.sending; }
- (NSNumber *)submitRelayCommand:(NSDictionary *)command {
    NSAssert([NSThread isMainThread], @"Use DrowsyWatchLink on main thread");
    if (!self.watchReady || ![command[@"watchSession"] isEqual:self.session]) return nil;
    NSNumber *capture = command[@"capturedAt"];
    if (![capture isKindOfClass:[NSNumber class]]) return nil;
    NSTimeInterval age = [NSDate date].timeIntervalSince1970 - capture.doubleValue;
    if (!isfinite(age) || age > 10 || age < -2) return nil;
    NSString *kind = command[@"type"];
    NSMutableDictionary *payload = [@{@"protocol": @1, @"source": @"phone_relay",
        @"session": self.session, @"sentAt": @((int32_t)floor(capture.doubleValue))} mutableCopy];
    if ([kind isEqual:@"model_result"]) {
        payload[@"type"] = @"model_result";
        payload[@"status"] = command[@"status"];
        payload[@"riskScore"] = command[@"riskScore"];
        payload[@"modelVersion"] = command[@"modelVersion"];
    } else if ([kind isEqual:@"camera_alert"]) {
        payload[@"type"] = @"alert"; payload[@"severity"] = command[@"severity"];
    } else if ([kind isEqual:@"camera_clear"]) {
        payload[@"type"] = @"clear";
    } else return nil;
    NSInteger seq = [[NSUserDefaults standardUserDefaults] integerForKey:@"DrowsyAlertSequence"] + 1;
    if (seq <= 0 || seq > INT32_MAX) return nil;
    [[NSUserDefaults standardUserDefaults] setInteger:seq forKey:@"DrowsyAlertSequence"];
    NSNumber *sequence = @((int32_t)seq); payload[@"sequence"] = sequence;
    self.sending = YES;
    NSInteger generation = self.generation;
    __weak typeof(self) weakSelf = self;
    [[ConnectIQ sharedInstance] sendMessage:payload toApp:self.app progress:^(uint32_t sent, uint32_t total) {}
        completion:^(IQSendMessageResult result) {
            dispatch_async(dispatch_get_main_queue(), ^{
                typeof(self) owner = weakSelf;
                if (!owner || owner.generation != generation) return;
                owner.sending = NO;
                if (owner.onTransportResult) owner.onTransportResult(sequence, result == IQSendMessageResult_Success);
            });
        } isTransient:YES];
    return sequence;
}
- (void)receivedMessage:(id)message fromApp:(IQApp *)app {
    if (![message isKindOfClass:[NSDictionary class]] || ![app.device.uuid isEqual:self.device.uuid]) return;
    NSDictionary *payload = message;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (![payload[@"protocol"] isEqual:@1]) return;
        if ([payload[@"type"] isEqual:@"telemetry"]) {
            if (![payload[@"session"] isEqual:self.session] || ![payload[@"schema"] isEqual:@1] ||
                ![payload[@"source"] isEqual:@"watch_sensors"]) return;
            if (![payload[@"sequence"] isKindOfClass:[NSNumber class]] ||
                ![payload[@"sentAt"] isKindOfClass:[NSNumber class]]) return;
            NSInteger seq = [payload[@"sequence"] integerValue];
            NSTimeInterval age = [NSDate date].timeIntervalSince1970 - [payload[@"sentAt"] doubleValue];
            if (seq <= self.lastTelemetrySequence || age > 10 || age < -2) return;
            self.lastTelemetrySequence = seq;
            if (self.onTelemetry) self.onTelemetry(payload);
            return;
        }
        if ([payload[@"type"] isEqual:@"hello_reply"] && [payload[@"status"] isEqual:@"ready"] &&
            [payload[@"session"] isKindOfClass:[NSString class]]) {
            if (![self.session isEqual:payload[@"session"]]) self.lastTelemetrySequence = 0;
            self.session = payload[@"session"]; [self status:@"Watch handshake ready"];
        } else if ([payload[@"status"] isEqual:@"wrong_session"]) {
            self.session = nil; [self status:@"Watch restarted; handshake required"];
        } else {
            [self status:[NSString stringWithFormat:@"Watch reply: %@", payload[@"status"] ?: payload[@"type"]]];
        }
        if (self.onWatchMessage) self.onWatchMessage(payload);
    });
}
- (void)stop {
    self.generation++; self.ready = NO; self.sending = NO; self.session = nil;
    [[ConnectIQ sharedInstance] unregisterForAllAppMessages:self];
    [[ConnectIQ sharedInstance] unregisterForAllDeviceEvents:self];
    self.app = nil; self.device = nil;
}
- (void)dealloc { [[ConnectIQ sharedInstance] unregisterForAllAppMessages:self]; [[ConnectIQ sharedInstance] unregisterForAllDeviceEvents:self]; }
@end
