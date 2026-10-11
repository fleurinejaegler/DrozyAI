#import "LocalModelLink.h"
@interface LocalModelLink ()
@property(nonatomic, strong) NSURLSession *session;
@property(nonatomic, strong) NSURLSessionDataTask *task;
@property(nonatomic, strong) NSTimer *timer;
@property(nonatomic, strong) NSURL *url;
@property(nonatomic, copy) NSString *token;
@property(nonatomic, copy) NSString *clientID;
@property(nonatomic, copy) NSString *relaySession;
@property(nonatomic, strong) NSDictionary *telemetry;
@property(nonatomic, strong) NSDictionary *state;
@property(nonatomic, strong) NSMutableArray *events;
@property(nonatomic) NSInteger generation;
@property(nonatomic) NSUInteger droppedEvents;
@end
@implementation LocalModelLink
- (instancetype)init {
    if ((self=[super init])) {
        self.events = [NSMutableArray array];
        NSURLSessionConfiguration *config = NSURLSessionConfiguration.ephemeralSessionConfiguration;
        config.timeoutIntervalForRequest = 5; config.timeoutIntervalForResource = 6;
        self.session = [NSURLSession sessionWithConfiguration:config];
    }
    return self;
}
- (void)status:(NSString *)status { if (self.onStatus) self.onStatus(status); }
- (void)connectURL:(NSURL *)url token:(NSString *)token clientID:(NSString *)clientID {
    [self disconnect];
    if (!([url.scheme isEqual:@"http"] || [url.scheme isEqual:@"https"]) || !url.host || url.user || url.password || url.query || url.fragment || token.length < 16 || clientID.length == 0) {
        [self status:@"Enter the laptop relay URL, pairing token (16+ characters), and client ID."]; return;
    }
    self.url = [url URLByAppendingPathComponent:@"api/phone/exchange"];
    self.token = token; self.clientID = clientID; self.relaySession = NSUUID.UUID.UUIDString;
    self.timer = [NSTimer scheduledTimerWithTimeInterval:1 target:self selector:@selector(exchange) userInfo:nil repeats:YES];
    [self status:@"Connecting to laptop relay…"]; [self exchange];
}
- (void)disconnect {
    self.generation++; [self.timer invalidate]; self.timer=nil; [self.task cancel]; self.task=nil;
    self.token=nil; self.url=nil; self.relaySession=nil; [self.events removeAllObjects];
    [self status:@"Laptop relay disconnected."];
}
- (void)consumeEvent:(NSDictionary *)event {
    if ([event[@"type"] isEqual:@"telemetry"]) { self.telemetry=event[@"payload"]; return; }
    if ([event[@"type"] isEqual:@"state"]) { self.state=event; return; }
    if (!self.url) return;
    [self.events addObject:event];
    if (self.events.count>32) { [self.events removeObjectAtIndex:0]; self.droppedEvents++; }
}
- (void)exchange {
    if (self.task || !self.url) return;
    NSArray *events=[self.events copy];
    NSDictionary *body=@{@"protocol":@1,@"clientId":self.clientID,@"relaySession":self.relaySession,
        @"watchSession":self.state[@"watchSession"] ?: NSNull.null,@"running":self.state[@"running"] ?: @NO,
        @"telemetry":self.telemetry ?: NSNull.null,@"events":events,@"droppedEvents":@(self.droppedEvents)};
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:self.url]; request.HTTPMethod=@"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    [request setValue:[@"Bearer " stringByAppendingString:self.token] forHTTPHeaderField:@"Authorization"];
    request.HTTPBody=[NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
    NSInteger generation=self.generation;
    __weak typeof(self) weakSelf=self;
    self.task=[self.session dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            typeof(self) owner=weakSelf;
            if (!owner || owner.generation!=generation) return;
            owner.task=nil;
            NSInteger status=[(NSHTTPURLResponse *)response statusCode];
            if (error || status!=200) { [owner status:error.localizedDescription ?: [NSString stringWithFormat:@"Laptop relay HTTP %ld",(long)status]]; return; }
            id payload=data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
            if (![payload isKindOfClass:NSDictionary.class] || ![payload[@"protocol"] isEqual:@1] || ![payload[@"commands"] isKindOfClass:NSArray.class]) {
                [owner status:@"Invalid laptop relay response."]; return;
            }
            // Remove only events actually included; keep new events accumulated during HTTP.
            for (NSDictionary *sent in events) [owner.events removeObjectIdenticalTo:sent];
            [owner status:@"Laptop relay connected."];
            NSArray *commands=payload[@"commands"];
            if (commands.count>8) { [owner status:@"Relay returned too many commands; rejected."]; return; }
            for (id command in commands) if ([command isKindOfClass:NSDictionary.class] && owner.onCommand) owner.onCommand(command);
        });
    }];
    [self.task resume];
}
- (void)dealloc { [self.timer invalidate]; [self.task cancel]; [self.session invalidateAndCancel]; }
@end
