#import "RelayProtocol.h"
#import <math.h>

@implementation RelayProtocol
+ (BOOL)number:(id)value {
    return [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID() && isfinite([value doubleValue]);
}
+ (NSString *)validate:(NSDictionary *)command watchSession:(NSString *)session now:(NSTimeInterval)now {
    if (![command isKindOfClass:NSDictionary.class] || ![command[@"protocol"] isEqual:@1]) return @"invalid_protocol";
    id identifier = command[@"commandId"];
    if (![identifier isKindOfClass:NSString.class] || [identifier length] == 0 || [identifier length] > 128) return @"invalid_command_id";
    if (!session || ![command[@"watchSession"] isEqual:session]) return @"wrong_session";
    id capture = command[@"capturedAt"];
    if (![self number:capture]) return @"invalid_timestamp";
    double age = now - [capture doubleValue];
    if (age > 10 || age < -2) return @"stale";
    id type = command[@"type"];
    if ([type isEqual:@"model_result"]) {
        id state = command[@"status"]; id score = command[@"riskScore"];
        if ([state isEqual:@"ready"]) {
            if (![self number:score] || [score doubleValue] < 0 || [score doubleValue] > 1) return @"invalid_score";
        } else if ([state isEqual:@"insufficient_data"] || [state isEqual:@"model_not_connected"]) {
            if (score != NSNull.null) return @"invalid_score";
        } else return @"invalid_model_status";
        id version = command[@"modelVersion"];
        if (![version isKindOfClass:NSString.class] || [version length] == 0 || [version length] > 64) return @"invalid_model_version";
        id input = command[@"inputTelemetrySequence"];
        if (![self number:input] || [input doubleValue] < 1 || floor([input doubleValue]) != [input doubleValue]) return @"invalid_input_sequence";
    } else if ([type isEqual:@"camera_alert"]) {
        if (![command[@"severity"] isEqual:@"warning"] && ![command[@"severity"] isEqual:@"high"]) return @"invalid_severity";
    } else if (![type isEqual:@"camera_clear"]) return @"invalid_type";
    return nil;
}
@end
