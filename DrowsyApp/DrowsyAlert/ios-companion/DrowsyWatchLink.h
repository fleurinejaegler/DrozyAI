#import <Foundation/Foundation.h>
#import <ConnectIQ/ConnectIQ.h>

// Add these two files to your existing iPhone camera/model target (ARC enabled).
// Call on main thread; retain this object for the lifetime of monitoring.
@interface DrowsyWatchLink : NSObject <IQDeviceEventDelegate, IQAppMessageDelegate>
@property(nonatomic, copy) void (^onStatus)(NSString *status);
@property(nonatomic, copy) void (^onWatchMessage)(NSDictionary *message);
// Watch telemetry uses NSNull for missing readings. Runs on the main queue.
@property(nonatomic, copy) void (^onTelemetry)(NSDictionary *telemetry);
@property(nonatomic, copy) void (^onTransportResult)(NSNumber *sequence, BOOL success);
@property(nonatomic, readonly, copy) NSString *watchSession;
@property(nonatomic, readonly) BOOL watchReady;
// Returns the watch sequence, or nil if not submitted. The host must await receipt.
- (NSNumber *)submitRelayCommand:(NSDictionary *)command;
- (instancetype)initWithURLScheme:(NSString *)scheme;
- (void)selectWatch;
- (NSArray<IQDevice *> *)devicesFromURL:(NSURL *)url;
- (void)attachDevice:(IQDevice *)device;
- (BOOL)sendDrowsinessSeverity:(NSString *)severity capturedAt:(NSDate *)captureTime;
- (BOOL)clearPhoneAlertCapturedAt:(NSDate *)captureTime;
- (void)heartbeat; // Host schedules every 5 seconds while foreground monitoring.
- (void)stop;
@end
