#import <Foundation/Foundation.h>
@interface LocalModelLink : NSObject
@property(nonatomic, copy) void (^onStatus)(NSString *status);
@property(nonatomic, copy) void (^onCommand)(NSDictionary *command);
- (void)connectURL:(NSURL *)url token:(NSString *)token clientID:(NSString *)clientID;
- (void)disconnect;
- (void)consumeEvent:(NSDictionary *)event;
@end
