#import "RelayViewController.h"
#import <WebKit/WebKit.h>
#import "LocalModelLink.h"

@interface RelayScriptProxy : NSObject <WKScriptMessageHandler>
@property(nonatomic, weak) id<WKScriptMessageHandler> target;
@end
@implementation RelayScriptProxy
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    [self.target userContentController:controller didReceiveScriptMessage:message];
}
@end

@interface RelayViewController () <WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate>
@property(nonatomic, strong) RelayCoordinator *relay;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) UILabel *statusLabel;
@property(nonatomic, strong) UILabel *websiteStatus;
@property(nonatomic, strong) NSURL *webRoot;
@property(nonatomic) BOOL pageReady;
@property(nonatomic) BOOL pausedByUser;
@property(nonatomic, strong) LocalModelLink *backend;
@property(nonatomic, strong) UITextField *serverURL;
@property(nonatomic, strong) UITextField *serverToken;
@property(nonatomic, strong) UILabel *serverStatus;
@end
@implementation RelayViewController
- (UIButton *)button:(NSString *)title action:(SEL)action {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
    [button setTitle:title forState:UIControlStateNormal]; [button addTarget:self action:action forControlEvents:UIControlEventTouchUpInside];
    return button;
}
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.relay = [RelayCoordinator new];
    self.backend = [LocalModelLink new];
    self.statusLabel = [UILabel new]; self.statusLabel.numberOfLines = 0; self.statusLabel.text = @"Select your Garmin watch. Keep both apps open.";
    self.statusLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleSubheadline];
    self.websiteStatus = [UILabel new]; self.websiteStatus.numberOfLines = 2;
    self.websiteStatus.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1];
    UIStackView *buttons = [[UIStackView alloc] initWithArrangedSubviews:@[
        [self button:@"Select watch" action:@selector(selectWatch)], [self button:@"Start" action:@selector(resumeByUser)],
        [self button:@"Pause" action:@selector(pauseByUser)], [self button:@"Reload page" action:@selector(loadPage)]]];
    buttons.distribution = UIStackViewDistributionFillEqually;
    self.serverURL = [UITextField new]; self.serverURL.borderStyle = UITextBorderStyleRoundedRect;
    self.serverURL.placeholder = @"Laptop URL: http://192.168.1.20:8765";
    self.serverURL.text = [NSUserDefaults.standardUserDefaults stringForKey:@"relayURL"];
    self.serverURL.keyboardType = UIKeyboardTypeURL; self.serverURL.autocapitalizationType = UITextAutocapitalizationTypeNone;
    self.serverURL.autocorrectionType = UITextAutocorrectionTypeNo;
    self.serverToken = [UITextField new]; self.serverToken.borderStyle = UITextBorderStyleRoundedRect;
    self.serverToken.placeholder = @"Pairing token from laptop terminal"; self.serverToken.secureTextEntry = YES;
    self.serverToken.autocorrectionType = UITextAutocorrectionTypeNo; self.serverToken.autocapitalizationType = UITextAutocapitalizationTypeNone;
    self.serverStatus = [UILabel new]; self.serverStatus.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1];
    self.serverStatus.numberOfLines = 2; self.serverStatus.text = @"Laptop relay disconnected • client ID: demo";
    UIStackView *serverButtons = [[UIStackView alloc] initWithArrangedSubviews:@[
        [self button:@"Connect laptop" action:@selector(connectLaptop)], [self button:@"Disconnect" action:@selector(disconnectLaptop)]]];
    serverButtons.distribution = UIStackViewDistributionFillEqually;
    UIStackView *header = [[UIStackView alloc] initWithArrangedSubviews:@[self.statusLabel, buttons, self.serverURL, self.serverToken, serverButtons, self.serverStatus, self.websiteStatus]];
    header.axis = UILayoutConstraintAxisVertical; header.spacing = 8; header.translatesAutoresizingMaskIntoConstraints = NO;
    WKWebViewConfiguration *config = [WKWebViewConfiguration new];
    config.allowsInlineMediaPlayback = YES; config.mediaTypesRequiringUserActionForPlayback = WKAudiovisualMediaTypeNone;
    RelayScriptProxy *proxy = [RelayScriptProxy new]; proxy.target = self;
    [config.userContentController addScriptMessageHandler:proxy name:@"drowsyRelay"];
    NSURL *bridge = [NSBundle.mainBundle URLForResource:@"bridge" withExtension:@"js" subdirectory:@"Web"];
    NSString *script = [NSString stringWithContentsOfURL:bridge encoding:NSUTF8StringEncoding error:nil];
    if (script) [config.userContentController addUserScript:[[WKUserScript alloc] initWithSource:script injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES]];
    self.webView = [[WKWebView alloc] initWithFrame:CGRectZero configuration:config];
    self.webView.navigationDelegate = self; self.webView.UIDelegate = self; self.webView.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:header]; [self.view addSubview:self.webView];
    [NSLayoutConstraint activateConstraints:@[
        [header.topAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.topAnchor constant:12],
        [header.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor constant:16],
        [header.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-16],
        [self.webView.topAnchor constraintEqualToAnchor:header.bottomAnchor constant:8],
        [self.webView.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor], [self.webView.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor],
        [self.webView.bottomAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.bottomAnchor]]];
    __weak typeof(self) weakSelf = self;
    self.relay.onStatus = ^(NSString *status) { weakSelf.statusLabel.text = status; };
    self.relay.onEvent = ^(NSDictionary *event) { [weakSelf deliver:event]; [weakSelf.backend consumeEvent:event]; };
    self.backend.onStatus = ^(NSString *status) { weakSelf.serverStatus.text = status; };
    self.backend.onCommand = ^(NSDictionary *command) { [weakSelf.relay receiveWebsiteCommand:command]; };
    [self loadPage]; [self.relay start];
}
- (void)loadPage {
    self.pageReady = NO;
    self.webRoot = [NSBundle.mainBundle URLForResource:@"Web" withExtension:nil];
    NSURL *index = [self.webRoot URLByAppendingPathComponent:@"index.html"];
    if (!self.webRoot || ![NSFileManager.defaultManager fileExistsAtPath:index.path]) {
        self.websiteStatus.text = @"Bundled Web/index.html is missing."; return;
    }
    self.websiteStatus.text = @"Loading local website…";
    [self.webView loadFileURL:index allowingReadAccessToURL:self.webRoot];
}
- (BOOL)trustedURL:(NSURL *)url {
    NSString *root = [self.webRoot.URLByResolvingSymlinksInPath.path stringByAppendingString:@"/"];
    return url.isFileURL && [url.URLByResolvingSymlinksInPath.path hasPrefix:root];
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))handler {
    handler([self trustedURL:action.request.URL] ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    self.pageReady = YES; self.websiteStatus.text = @"Local website ready • model supplied by your team";
    [self.relay publishState];
}
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    self.pageReady = NO; self.websiteStatus.text = error.localizedDescription;
}
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    [self webView:webView didFailNavigation:navigation withError:error];
}
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)webView {
    self.pageReady = NO; self.websiteStatus.text = @"Website stopped. Reload the page.";
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    if (!self.pageReady || !message.frameInfo.mainFrame || ![self trustedURL:message.frameInfo.request.URL]) return;
    [self.relay receiveWebsiteCommand:message.body];
}
- (void)deliver:(NSDictionary *)event {
    if (!self.pageReady) return; // Live-only: never build a backlog while page loads.
    NSData *json = [NSJSONSerialization dataWithJSONObject:event options:NSJSONWritingFragmentsAllowed error:nil];
    if (!json) return;
    NSString *literal = [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding];
    [self.webView evaluateJavaScript:[NSString stringWithFormat:@"window.DrowsyRelay._receive(%@)", literal] completionHandler:^(id value, NSError *error) {
        if (error) self.websiteStatus.text = @"Website bridge unavailable. Reload the page.";
    }];
}
- (void)webView:(WKWebView *)webView requestMediaCapturePermissionForOrigin:(WKSecurityOrigin *)origin initiatedByFrame:(WKFrameInfo *)frame type:(WKMediaCaptureType)type decisionHandler:(void (^)(WKPermissionDecision))handler API_AVAILABLE(ios(15.0)) {
    // Only the bundled top-level page may request capture; iOS still asks permission.
    handler(frame.mainFrame && [self trustedURL:frame.request.URL] && type == WKMediaCaptureTypeCamera ? WKPermissionDecisionGrant : WKPermissionDecisionDeny);
}
- (void)selectWatch { [self.relay selectWatch]; }
- (void)selectDevicesFromURL:(NSURL *)url {
    NSArray<IQDevice *> *devices = [self.relay devicesFromURL:url];
    if (devices.count == 0) { self.statusLabel.text = @"No shared watch. Pair it in Garmin Connect, then select again."; return; }
    UIAlertController *picker = [UIAlertController alertControllerWithTitle:@"Choose your watch" message:nil preferredStyle:UIAlertControllerStyleAlert];
    for (IQDevice *device in devices) {
        [picker addAction:[UIAlertAction actionWithTitle:device.friendlyName ?: device.modelName style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) {
            self.pausedByUser = NO; [self.relay attach:device];
        }]];
    }
    [picker addAction:[UIAlertAction actionWithTitle:@"Cancel" style:UIAlertActionStyleCancel handler:nil]];
    [self presentViewController:picker animated:YES completion:nil];
}
- (void)pauseByUser { self.pausedByUser = YES; [self pauseRelay]; }
- (void)resumeByUser { self.pausedByUser = NO; [self resumeRelay]; }
- (void)pauseRelay {
    [self.relay pause];
    [self.backend disconnect];
    [self.webView evaluateJavaScript:@"window.dispatchEvent(new Event('drowsy:pause'))" completionHandler:nil];
}
- (void)resumeRelay { if (!self.pausedByUser) [self.relay start]; }
- (void)connectLaptop {
    [self.view endEditing:YES];
    NSURL *url = [NSURL URLWithString:self.serverURL.text];
    if (!url) { self.serverStatus.text = @"Enter a valid laptop relay URL."; return; }
    [NSUserDefaults.standardUserDefaults setObject:self.serverURL.text forKey:@"relayURL"];
    [self.backend connectURL:url token:self.serverToken.text clientID:@"demo"];
    [self.relay publishState];
}
- (void)disconnectLaptop { [self.backend disconnect]; }
- (void)dealloc { [self.webView.configuration.userContentController removeScriptMessageHandlerForName:@"drowsyRelay"]; [self.relay pause]; }
@end
