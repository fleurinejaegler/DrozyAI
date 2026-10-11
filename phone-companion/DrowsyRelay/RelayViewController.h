#import <UIKit/UIKit.h>
#import "RelayCoordinator.h"
@interface RelayViewController : UIViewController
- (void)selectDevicesFromURL:(NSURL *)url;
- (void)pauseRelay;
- (void)resumeRelay;
@end
