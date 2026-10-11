#import <XCTest/XCTest.h>
#import "RelayProtocol.h"
@interface RelayProtocolTests : XCTestCase @end
@implementation RelayProtocolTests
- (NSMutableDictionary *)score {
    return [@{@"protocol":@1,@"commandId":@"test-1",@"watchSession":@"session-1",@"capturedAt":@1000,
        @"type":@"model_result",@"status":@"ready",@"riskScore":@0.75,@"modelVersion":@"reference-v1",@"inputTelemetrySequence":@12} mutableCopy];
}
- (void)testValidScore {
    XCTAssertNil([RelayProtocol validate:self.score watchSession:@"session-1" now:1005]);
}
- (void)testMissingAndOutOfRangeScores {
    NSMutableDictionary *message = self.score; message[@"riskScore"] = @75;
    XCTAssertEqualObjects([RelayProtocol validate:message watchSession:@"session-1" now:1005], @"invalid_score");
    message[@"riskScore"] = NSNull.null;
    XCTAssertEqualObjects([RelayProtocol validate:message watchSession:@"session-1" now:1005], @"invalid_score");
    message[@"status"] = @"insufficient_data";
    XCTAssertNil([RelayProtocol validate:message watchSession:@"session-1" now:1005]);
    message[@"riskScore"] = @YES;
    XCTAssertEqualObjects([RelayProtocol validate:message watchSession:@"session-1" now:1005], @"invalid_score");
}
- (void)testFreshnessAndSession {
    XCTAssertEqualObjects([RelayProtocol validate:self.score watchSession:@"session-1" now:1011], @"stale");
    XCTAssertEqualObjects([RelayProtocol validate:self.score watchSession:@"session-1" now:997], @"stale");
    XCTAssertEqualObjects([RelayProtocol validate:self.score watchSession:@"old-session" now:1005], @"wrong_session");
}
- (void)testIndependentCameraCommand {
    NSMutableDictionary *message = self.score;
    message[@"type"] = @"camera_alert"; message[@"severity"] = @"high";
    [message removeObjectForKey:@"inputTelemetrySequence"]; [message removeObjectForKey:@"riskScore"];
    XCTAssertNil([RelayProtocol validate:message watchSession:@"session-1" now:1005]);
    message[@"severity"] = @"low";
    XCTAssertEqualObjects([RelayProtocol validate:message watchSession:@"session-1" now:1005], @"invalid_severity");
}
@end
