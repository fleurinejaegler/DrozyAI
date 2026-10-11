// Run the actual Objective-C watch link against a fake Garmin transport.
// These checks exercise scheduling, discovery, receipts and reconnect races.
#import <Foundation/Foundation.h>
#import "DrowsyWatchLink.h"

NSString * const IQGCMBundle = @"com.garmin.connect.mobile";
NSString * const IQGCMInternalBetaBundle = @"com.garmin.connect.mobile.beta";
int const IQSDKVersion = 0;
NSString *NSStringFromSendMessageResult(IQSendMessageResult value) { return [@(value) stringValue]; }

@interface IQDevice ()
@property(nonatomic, readwrite, strong) NSUUID *uuid;
@end
@implementation IQDevice
+ (BOOL)supportsSecureCoding { return YES; }
- (instancetype)initWithCoder:(NSCoder *)coder { return [super init]; }
- (void)encodeWithCoder:(NSCoder *)coder {}
@end
@interface IQApp ()
@property(nonatomic, readwrite, strong) IQDevice *device;
@end
@implementation IQApp
+ (instancetype)appWithUUID:(NSUUID *)uuid storeUuid:(NSUUID *)store device:(IQDevice *)device {
    IQApp *app = [IQApp new]; app.device = device; return app;
}
+ (BOOL)supportsSecureCoding { return YES; }
- (instancetype)initWithCoder:(NSCoder *)coder { return [super init]; }
- (void)encodeWithCoder:(NSCoder *)coder {}
@end

@interface ConnectIQ ()
@property(nonatomic, strong) NSMutableArray<NSDictionary *> *sent;
@property(nonatomic, strong) NSMutableArray *completions;
@property(nonatomic) IQDeviceStatus testStatus;
@end
@implementation ConnectIQ
+ (instancetype)sharedInstance {
    static ConnectIQ *sdk; static dispatch_once_t once;
    dispatch_once(&once, ^{ sdk = [self alloc]; sdk.sent = [NSMutableArray array]; sdk.completions = [NSMutableArray array]; });
    return sdk;
}
- (void)initializeWithUrlScheme:(NSString *)scheme uiOverrideDelegate:(id<IQUIOverrideDelegate>)delegate {}
- (void)registerForDeviceEvents:(IQDevice *)device delegate:(id<IQDeviceEventDelegate>)delegate {}
- (void)registerForAppMessages:(IQApp *)app delegate:(id<IQAppMessageDelegate>)delegate {}
- (void)unregisterForAllAppMessages:(id<IQAppMessageDelegate>)delegate {}
- (void)unregisterForAllDeviceEvents:(id<IQDeviceEventDelegate>)delegate {}
- (IQDeviceStatus)getDeviceStatus:(IQDevice *)device { return self.testStatus; }
- (void)sendMessage:(id)message toApp:(IQApp *)app progress:(IQSendMessageProgress)progress completion:(IQSendMessageCompletion)completion isTransient:(BOOL)transient {
    [self.sent addObject:message]; [self.completions addObject:[completion copy]];
}
@end

static int checks = 0;
static void check(BOOL ok, NSString *reason) {
    if (!ok) { fprintf(stderr, "FAIL: %s\n", reason.UTF8String); exit(1); }
    checks++;
}
static void drain(void) {
    [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.03]];
}
static void complete(ConnectIQ *sdk, NSUInteger index, IQSendMessageResult result) {
    IQSendMessageCompletion callback = sdk.completions[index]; callback(result); drain();
}
static void reply(DrowsyWatchLink *link, IQDevice *device) {
    IQApp *app = [IQApp appWithUUID:NSUUID.UUID storeUuid:nil device:device];
    [link receivedMessage:@{@"protocol": @1, @"type": @"hello_reply", @"status": @"ready", @"session": @"test-session"} fromApp:app];
    drain();
}

int main(void) { @autoreleasepool {
    ConnectIQ *sdk = ConnectIQ.sharedInstance;
    DrowsyWatchLink *link = [[DrowsyWatchLink alloc] initWithURLScheme:@"test"];
    __block NSInteger statuses = 0;
    link.onStatus = ^(NSString *status) { statuses++; };
    [link heartbeat];
    check(sdk.sent.count == 0 && statuses == 0, @"No watch selected: a keepalive stays silent");
    IQDevice *device = [IQDevice new]; device.uuid = NSUUID.UUID;
    [link attachDevice:device]; sdk.testStatus = IQDeviceStatus_NotConnected;
    [link heartbeat];
    check(sdk.sent.count == 0 && [link.connectionStatus containsString:@"Bluetooth connection"], @"Disconnected keepalive reports connection stage without sending");
    sdk.testStatus = IQDeviceStatus_Connected;
    [link deviceStatusChanged:device status:IQDeviceStatus_Connected]; [link heartbeat];
    check(sdk.sent.count == 0, @"Connected callback alone cannot send before characteristics discovery");
    [link deviceCharacteristicsDiscovered:device];
    check(sdk.sent.count == 1 && [sdk.sent.lastObject[@"type"] isEqual:@"hello"], @"Discovery initiates one hello");
    NSString *discoveryStatus = link.connectionStatus;
    [link heartbeat]; [link heartbeat];
    check(sdk.sent.count == 1 && [link.connectionStatus isEqual:discoveryStatus], @"Busy keepalives neither overlap sends nor overwrite useful status");
    complete(sdk, 0, IQSendMessageResult_Success);
    check(!link.watchReady && link.watchSession == nil, @"Bluetooth send success alone does not prove watch readiness");
    reply(link, device);
    check(link.watchReady && [link.watchSession isEqual:@"test-session"], @"Actual hello reply establishes session");
    [link heartbeat];
    check(sdk.sent.count == 2 && [sdk.sent.lastObject[@"type"] isEqual:@"heartbeat"] && [sdk.sent.lastObject[@"session"] isEqual:@"test-session"], @"Ready session sends session-bound heartbeat");
    [link heartbeat];
    check(sdk.sent.count == 2, @"Outstanding heartbeat blocks another send");
    [link attachDevice:device]; [link deviceCharacteristicsDiscovered:device];
    check(sdk.sent.count == 3, @"Reselecting a watch starts a new hello");
    complete(sdk, 1, IQSendMessageResult_Success); [link heartbeat];
    check(sdk.sent.count == 3, @"Old completion cannot clear a new connection's busy flag");
    complete(sdk, 2, IQSendMessageResult_Failure_AppNotFound);
    check([link.connectionStatus containsString:@"not found"], @"Missing watch app produces actionable error");
    [link heartbeat]; complete(sdk, 3, IQSendMessageResult_Success); reply(link, device);
    check(link.watchReady, @"Handshake can recover after a failed send");
    check(![link sendDrowsinessSeverity:@"high" capturedAt:[NSDate dateWithTimeIntervalSinceNow:-30]], @"Old alert is still rejected");
    check([link sendDrowsinessSeverity:@"high" capturedAt:NSDate.date], @"Fresh alert submits after actual handshake");
    check([sdk.sent.lastObject[@"type"] isEqual:@"alert"] && [sdk.sent.lastObject[@"severity"] isEqual:@"high"], @"Alert envelope retains severity");
    [link deviceStatusChanged:device status:IQDeviceStatus_NotConnected];
    check(!link.watchReady && !link.watchSession, @"Disconnect invalidates handshake");
    fprintf(stdout, "%d watch-link behavior checks passed (fake Bluetooth; real watch not implied).\n", checks);
} return 0; }
