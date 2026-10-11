#import <Foundation/Foundation.h>

@interface RelayProtocol : NSObject
+ (NSString *)validate:(NSDictionary *)command watchSession:(NSString *)session now:(NSTimeInterval)now;
@end
