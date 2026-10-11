#import <UIKit/UIKit.h>
#import "RelayViewController.h"

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation AppDelegate
- (BOOL)application:(UIApplication *)app didFinishLaunchingWithOptions:(NSDictionary *)options {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [[RelayViewController alloc] init];
    [self.window makeKeyAndVisible]; return YES;
}
- (BOOL)application:(UIApplication *)app openURL:(NSURL *)url options:(NSDictionary<UIApplicationOpenURLOptionsKey,id> *)options {
    NSString *source = options[UIApplicationOpenURLOptionsSourceApplicationKey];
    if (![url.scheme isEqual:@"drowsyrelay-ciq"] || ![source isEqual:IQGCMBundle]) return NO;
    [(RelayViewController *)self.window.rootViewController selectDevicesFromURL:url]; return YES;
}
- (void)applicationDidEnterBackground:(UIApplication *)app { [(RelayViewController *)self.window.rootViewController pauseRelay]; }
- (void)applicationDidBecomeActive:(UIApplication *)app { [(RelayViewController *)self.window.rootViewController resumeRelay]; }
@end
