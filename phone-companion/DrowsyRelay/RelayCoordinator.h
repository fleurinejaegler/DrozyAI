#import <Foundation/Foundation.h>
#import "DrowsyWatchLink.h"

@interface RelayCoordinator : NSObject
@property(nonatomic, strong, readonly) DrowsyWatchLink *watch;
@property(nonatomic, copy) void (^onEvent)(NSDictionary *event);
@property(nonatomic, copy) void (^onStatus)(NSString *status);
- (void)start;
- (void)pause;
- (void)selectWatch;
- (NSArray<IQDevice *> *)devicesFromURL:(NSURL *)url;
- (void)attach:(IQDevice *)device;
- (void)receiveWebsiteCommand:(id)command;
- (void)publishState;
@end
