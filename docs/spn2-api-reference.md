#  Save Page Now 2 Public API Docs Draft

Vangelis Banos, updated: 2025-10-22

Capture a web page as it appears now for use as a trusted citation in the future. Changelog: [https://docs.google.com/document/d/19RJsRncGUw2qHqGGg9lqYZYf7KKXMDL1Mro5o1Qw6QI/edit\#](https://docs.google.com/document/d/19RJsRncGUw2qHqGGg9lqYZYf7KKXMDL1Mro5o1Qw6QI/edit#)

Contents

[**Glossary**](#glossary)	**[1](#glossary)**

[**Basic API Reference**](#basic-api-reference)	**[1](#basic-api-reference)**

[Capture request](#capture-request)	[1](#capture-request)

[Status request](#status-request)	[3](#status-request)

[Error codes](#error-codes)	[5](#error-codes)

[User status](#user-status)	[7](#user-status)

[**System status**](#system-status)	**[7](#system-status)**

[**Tips for faster captures**](#tips-for-faster-captures)	**[7](#tips-for-faster-captures)**

[**Limitations**](#limitations)	**[8](#limitations)**

[**Example PHP script using the SPN2 API to capture a URL**](#example-php-script-using-the-spn2-api-to-capture-a-url)	**[9](#example-php-script-using-the-spn2-api-to-capture-a-url)**

[**Frequently Asked Questions**](#frequently-asked-questions)	**[10](#frequently-asked-questions)**

# Glossary {#glossary}

| Capture | A record in the Wayback Machine that can be accessed like this: [http://web.archive.org/web/20051231203615/http://www.bbc.co.uk/](http://web.archive.org/web/20051231203615/http://www.bbc.co.uk/)  |
| :---- | :---- |
| Timestamp | A datetime format used in the Wayback Machine: YYYYMMDDHHMMSS. Example: 20051231203615 |
| Embeds | Components of a web page, e.g. images, CSS, JS, etc. When we capture a web page, we also try to capture its embeds. We return them with the capture result. |
| Outlinks | Links found inside the capture. We return them with the capture result. |

# Basic API Reference {#basic-api-reference}

The Save Page Now 2 (SPN2) API enables you to make a **capture request** and then check its progress with a **status request**.

## Capture request {#capture-request}

SPN2 runs on [https://web.archive.org/save](https://web.archive.org/save) which requires authentication using two alternative methods:

1. **S3 API Keys** (highly preferable). Get your account’s keys at [https://archive.org/account/s3.php](https://archive.org/account/s3.php) Use HTTP Header *"**authorization: LOW myaccesskey:mysecret**"* in your requests.
2. Cookies: Get **logged-in-sig** and **logged-in-user** from your browser when you log in to [https://archive.org](https://archive.org) and add them to your SPN2 HTTP requests. Cookies are not desirable because they tend to expire after a few days so you would need to login again to archive.org to get new cookies.

To capture a web page via the API, you can use an HTTP POST or GET request as follows:

| curl \-X POST \-H "Accept: application/json" \-H "Authorization: LOW myaccesskey:mysecret" \-d'url=[http://brewster.kahle.org/](http://brewster.kahle.org/)' [https://web.archive.org/save](https://web.archive.org/save) or curl \-X GET \-H "Accept: application/json" \--cookie "logged-in-sig=xxx;logged-in-user=user1%40archive.org;" https://web.archive.org/save/http://brewster.kahle.org/ |
| :---- |

**Additional capture request options (HTTP POST required)**.

**Important note:** Anything other than "1" or "on" is considered to be "off". If you use "01" or "True" it means "off".

| Parameter | Description |
| :---- | :---- |
| capture\_all=1 | Archive page even when the server returns an HTTP error status (4xx or 5xx). By default, only pages with HTTP status 200 OK are captured. |
| capture\_outlinks=1 | Automatically archive links found on the target page. Also applies to links discovered in PDF, JSON, epub, RSS and MRSS documents. |
| capture\_screenshot=1 | Generate and archive a full-page PNG screenshot of the target page. The screenshot is stored as a separate capture. |
| delay\_wb\_availability=1 | The capture becomes available in the Wayback Machine after \~12 hours instead of immediately. This helps reduce system load. API responses remain the same. |
| force\_get=1 | Always use an HTTP GET request for the capture. By default SPN2 does a HTTP HEAD request first to determine when a headless browser or a simple HTTP GET request is required. force\_get overrides this behavior. |
| skip\_first\_archive=1 | Skip checking if a capture is a first. Enable this option if you don’t need this information to improve performance. |
| if\_not\_archived\_within=\<timedelta\> | Capture the web page only if the most recent capture is older than the specified limit. The limit format could be any datetime expression like "3d 5h 20m" or just a number of seconds, e.g. "120". If a newer capture already exists, SPN2 returns that as a recent capture instead of creating a new one. The default interval is 1 hour. |
| if\_not\_archived\_within= \<timedelta1\>,\<timedelta2\> | When using 2 comma separated \<timedelta\> values, the first one applies to the main capture and the second one applies to outlinks. |
| outlinks\_availability=1 | Include the timestamp of the last capture for all outlinks. |
| email\_result=1 | Send an email report of the captured URLs to the Patron’s email. |
| js\_behavior\_timeout=\<N\> | Run JS code for \<N\> seconds after page load to trigger target page functionality like image loading on mouse over, scroll down to load more content, etc. The default is 5 seconds and the maximum is 30 seconds. Set 0 to disable JS execution and speed up the capture. More details on the JS code we execute: [https://github.com/internetarchive/brozzler/blob/master/brozzler/behaviors.yaml](https://github.com/internetarchive/brozzler/blob/master/brozzler/behaviors.yaml) |
| capture\_cookie=\<XXX\> | Use extra HTTP Cookie value when capturing the target page. Useful for capturing content that depends on session or authentication cookies. |
| use\_user\_agent=\<XXX\> | Use a custom HTTP User-Agent value when capturing the target page.  |
| target\_username=\<XXX\> target\_password=\<YYY\> | Use your own username and password in the target page’s login forms.This can be used to archive content that requires authentication. |

Example

| curl \-X POST \-H "Accept: application/json" \-d'url=http://brewster.kahle.org/\&capture\_outlinks=1\&capture\_all=1'  \-H "Authorization: LOW myaccesskey:mysecret" [https://web.archive.org/save](http://vbanos-dev.us.archive.org:8092/save) |
| :---- |

In any case, a capture request might return:

| {"url":"[http://brewster.kahle.org/](http://brewster.kahle.org/)", "job\_id":"ac58789b-f3ca-48d0-9ea6-1d1225e98695"} |
| :---- |

## Status request {#status-request}

It is possible to see the status of one or multiple captures via the API. Note that the status API result is available for a limited time due to system memory limitations. Please try to check job status within 1 hour after performing a capture request.

To see a capture status, you can use an HTTP GET or POST request as follows:

| curl \-X GET \-H "Accept: application/json" \-H "Authorization: LOW myaccesskey:mysecret" [https://web.archive.org/save/status/ac58789b-f3ca-48d0-9ea6-1d1225e98695](https://web.archive.org/save/status/ac58789b-f3ca-48d0-9ea6-1d1225e98695) or curl \-X POST \-H "Accept: application/json" \-d'job\_id=ac58789b-f3ca-48d0-9ea6-1d1225e98695' \--cookie "logged-in-sig=AAAAAAAAAA;logged-in-user=user1%40archive.org;" [https://web.archive.org/save/status](https://web.archive.org/save/status) |
| :---- |

In any case, a capture status request might return the following if successful:

|   {"status":"success",   "job\_id":"ac58789b-f3ca-48d0-9ea6-1d1225e98695",   "original\_url":"[http://brewster.kahle.org/](http://brewster.kahle.org/)",    "screenshot":"http://web.archive.org/screenshot/http://brewster.kahle.org/"   "timestamp":"20180326070330",   "duration\_sec":6.203,   "resources":\[        "http://brewster.kahle.org/",      "http://brewster.kahle.org/favicon.ico",      "http://brewster.kahle.org/files/2011/07/bkheader-follow.jpg",      "http://brewster.kahle.org/files/2016/12/amazon-unhappy.jpg",      "http://brewster.kahle.org/files/2017/01/computer-1294045\_960\_720-300x300.png",      "http://brewster.kahle.org/files/2017/11/20thcenturytimemachineimages\_0000.jpg",      "http://brewster.kahle.org/files/2018/02/IMG\_6041-1-300x225.jpg",      "http://brewster.kahle.org/files/2018/02/IMG\_6061-768x1024.jpg",      "http://brewster.kahle.org/files/2018/02/IMG\_6103-300x225.jpg",      "http://brewster.kahle.org/files/2018/02/IMG\_6132-225x300.jpg",      "http://brewster.kahle.org/files/2018/02/IMG\_6138-1-300x225.jpg",      "http://brewster.kahle.org/wp-content/themes/twentyten/images/wordpress.png",      "http://brewster.kahle.org/wp-content/themes/twentyten/style.css",      "http://brewster.kahle.org/wp-includes/js/wp-embed.min.js?ver=4.9.4",      "http://brewster.kahle.org/wp-includes/js/wp-emoji-release.min.js?ver=4.9.4",      "http://platform.twitter.com/widgets.js",      "https://archive-it.org/piwik.js",      "https://platform.twitter.com/jot.html",      "https://platform.twitter.com/js/button.556f0ea0e4da4e66cfdc182016dbd6db.js",      "https://platform.twitter.com/widgets/follow\_button.f47a2e0b4471326b6fa0f163bda46011.en.html",      "https://syndication.twitter.com/settings",      "https://www.syndikat.org/en/joint\_venture/embed/",      "https://www.syndikat.org/wp-admin/images/w-logo-blue.png",      "https://www.syndikat.org/wp-content/plugins/user-access-manager/css/uamAdmin.css?ver=1.0",      "https://www.syndikat.org/wp-content/plugins/user-access-manager/css/uamLoginForm.css?ver=1.0",      "https://www.syndikat.org/wp-content/plugins/user-access-manager/js/functions.js?ver=4.9.4",      "https://www.syndikat.org/wp-content/plugins/wysija-newsletters/css/validationEngine.jquery.css?ver=2.8.1",      "https://www.syndikat.org/wp-content/uploads/2017/11/s\_miete\_fr-200x116.png",      "https://www.syndikat.org/wp-includes/js/jquery/jquery-migrate.min.js?ver=1.4.1",      "https://www.syndikat.org/wp-includes/js/jquery/jquery.js?ver=1.12.4",      "[https://www.syndikat.org/wp-includes/js/wp-emoji-release.min.js?ver=4.9.4](https://www.syndikat.org/wp-includes/js/wp-emoji-release.min.js?ver=4.9.4)"    \],    "outlinks":{       "[https://archive.org/](http://archive.org/)": "xxxxxx89b-f3ca-48d0-9ea6-1d1225e98695",       "[https://other.com](https://other.com)": "yyyy89b-f3ca-48d0-9ea6-1d1225e98695"   }} |
| :---- |

Note that *"original\_url":"[http://brewster.kahle.org/](http://brewster.kahle.org/)"* contains the final URL **after following potential redirects**.

Note that *"screenshot":"[http://web.archive.org/screenshot/http://brewster.kahle.org/](http://web.archive.org/screenshot/http://brewster.kahle.org/)"* is included in the response only when we use **capture\_screenshot=1**. In case there is a screenshot capture error, the result doesn’t include a "screenshot" field.

When **outlinks\_availability=1** option is used, the outlinks would be like the following:

| "outlinks":{       "[https://archive.org/](http://archive.org/)": {"timestamp": "20180102005040"},       "[https://other.com](https://other.com)": {"timestamp": "20190102005040"},       "[https://other-not-captured.com](https://other-not-captured.com)": {"timestamp": null}   } |
| :---- |

In case the capture is pending, it may return:

| {"status":"pending",   "job\_id":"e70f33c7-9eca-4c88-826d-26930564d7c8",   "resources":\[     "[https://ajax.googleapis.com/ajax/libs/jquery/1.7.2/jquery.min.js](https://ajax.googleapis.com/ajax/libs/jquery/1.7.2/jquery.min.js)",     "[https://ajax.googleapis.com/ajax/libs/jqueryui/1.8.21/jquery-ui.min.js](https://ajax.googleapis.com/ajax/libs/jqueryui/1.8.21/jquery-ui.min.js)",     "[https://cdn.onesignal.com/sdks/OneSignalSDK.js](https://cdn.onesignal.com/sdks/OneSignalSDK.js)",   \] } |
| :---- |

In case there is an error, it may return:

| {"status":"error",   "exception":"\[Errno \-2\] Name or service not known",   "status\_ext":"error:invalid-host-resolution",   "job\_id":"2546c79b-ec70-4bec-b78b-1941c42a6374",   "message":"Couldn't resolve host for [http://example5123.com](http://example5123.com).",   "resources": \[\] } |
| :---- |

### Error codes {#error-codes}

The error codes and messages may vary depending on the problem. Field **status\_ext** contains more information on the specific error type.

| status\_ext | Description |
| :---- | :---- |
| error:bad-gateway | Bad Gateway for URL (HTTP status=502). |
| error:bad-request | The server could not understand the request due to invalid syntax. (HTTP status=401) |
| error:bandwidth-limit-exceeded | The target server has exceeded the bandwidth specified by the server administrator. (HTTP status=509). |
| error:blocked | The target site is blocking us (HTTP status=999). |
| error:blocked-client-ip | Anonymous clients which are listed in [https://www.spamhaus.org/xbl/](https://www.spamhaus.org/xbl/) or [https://www.spamhaus.org/sbl/](https://www.spamhaus.org/sbl/) lists (spams & exploits) are blocked. Tor exit nodes are excluded from this filter. |
| error:blocked-url | We use a URL block list based on Mozilla web tracker lists to avoid unwanted captures. |
| error:browsing-timeout | SPN2 back-end headless browser timeout. |
| error:capture-location-error | SPN2 back-end cannot find the created capture location. (system error). |
| error:cannot-fetch | Cannot fetch the target URL due to system overload. |
| error:celery | Cannot start capture task. |
| error:filesize-limit | Cannot capture web resources over 2GB. |
| error:ftp-access-denied | Tried to capture an FTP resource but access was denied. |
| error:gateway-timeout | The target server didn't respond in time. (HTTP status=504). |
| error:http-version-not-supported | The target server does not support the HTTP protocol version used in the request for URL (HTTP status=505). |
| error:internal-server-error | SPN internal server error. |
| error:invalid-url-syntax | Target URL syntax is not valid. |
| error:invalid-server-response | The target server response was invalid. (e.g. invalid headers, invalid content encoding, etc). |
| error:invalid-host-resolution | Couldn’t resolve the target host. |
| error:job-failed | Capture failed due to system error. |
| error:method-not-allowed | The request method is known by the server but has been disabled and cannot be used (HTTP status=405). |
| error:not-implemented | The request method is not supported by the server and cannot be handled (HTTP status=501). |
| error:no-browsers-available | SPN2 back-end headless browser cannot run. |
| error:network-authentication-required | The client needs to authenticate to gain network access to the URL (HTTP status=511). |
| error:no-access | Target URL could not be accessed (status=403). |
| error:not-found | Target URL not found (status=404). |
| error:not-implemented | The request method is not supported by the server and cannot be handled for URL (HTTP status=501). |
| error:proxy-error | SPN2 back-end proxy error. |
| error:protocol-error | HTTP connection broken. (A possible cause of this error is "IncompleteRead"). |
| error:read-timeout | HTTP connection read timeout. |
| error:soft-time-limit-exceeded | Capture duration exceeded 45s time limit and was terminated. |
| error:service-unavailable | Service unavailable for URL (HTTP status=503). |
| error:too-many-daily-captures | This URL has been captured 10 times today. We cannot make any more captures. |
| error:too-many-redirects | Too many redirects. SPN2 tries to follow 3 redirects automatically. |
| error:too-many-requests | The target host has received too many requests from SPN and it is blocking it. (HTTP status=429). Note that captures to the same host will be delayed for 10-20s after receiving this response to remedy the situation. |
| error:user-session-limit | User has reached the limit of concurrent active capture sessions. |
| error:unauthorized | The server requires authentication (HTTP status=401). |
| error:max-daily-bandwidth | An authenticated user can archive up to 5GB per day. |
| error:max-daily-bandwidth-from-ip | An anonymous user can archive up to 2GB per day. |
| error:max-daily-bandwidth-host | SPN2 can archive up to 100GB per day from a host. |

In case you used option \`capture\_outlinks=1\`, the result outlinks include the job\_id for each outlink so that you could check its status later. Else, outlinks key contains the list of URLs only.

You can access the created capture using the following URL pattern:

| https://web.archive.org/web/\<timestamp\>/\<original\_url\> |
| :---- |

**Advanced status request usage**
To see the status of **multiple captures**, use parameter **job\_ids** and a comma separated list of values:

| curl \-X POST \-H "Accept: application/json" \-d'job\_ids=ac58789b-f3ca-48d0-9ea6-1d1225e98695,ac58789b-f3ca-48d0-9ea6-xxxxxx, ac58789b-f3ca-48d0-9ea6-yyyyyyyyy' \--cookie "logged-in-sig=AAAAAAAAAA;logged-in-user=user1%40archive.org;" [https://web.archive.org/save/status](https://web.archive.org/save/status) |
| :---- |

To see the capture status of all outlinks, use parameter **job\_id\_outlinks** and the job\_id of the parent capture:

| curl \-X POST \-H "Accept: application/json" \-d'job\_id\_outlinks=ac58789b-f3ca-48d0-9ea6-1d1225e98695' \--cookie "logged-in-sig=AAAAAAAAAA;logged-in-user=user1%40archive.org;" [https://web.archive.org/save/status](https://web.archive.org/save/status) |
| :---- |

## User status {#user-status}

You can see the current number of active and available session of your user account using the following:

| curl \-X GET \-H "Accept: application/json" \-H "Authorization: LOW myaccesskey:mysecret" http://web.archive.org/save/status/user |
| :---- |

To avoid getting a stale cache response, it is better to use a URL like this: [http://web.archive.org/save/status/user?\_t=1602606392499](http://web.archive.org/save/status/user?_t=1602606392499) where \_t is a random variable.

The response will be like:

| {"available":12,"processing":3} |
| :---- |

## System status {#system-status}

You can check if the service is overloaded using the following:

| curl \-X GET \-H "Accept: application/json" http://web.archive.org/save/status/system |
| :---- |

If everything is fine, it may return:

| {"status":"ok"} |
| :---- |

If the service is overloaded, it may return:

| {"status":"Save Page Now servers are temporarily overloaded. Your captures may be delayed."} |
| :---- |

To be clear, SPN will still work fine in this case, besides some delays.

If there is a critical problem, there will be an HTTP status=502 response.

# Tips for faster captures {#tips-for-faster-captures}

The following options can significantly reduce capture time:

* Use **skip\_first\_archive=1** if you do not need to know whether the capture is the first archived copy.
* Use **force\_get=1** when the target URL is not an HTML page and can be retrieved with a simple HTTP request.
* Use **js\_behavior\_timeout=0** for pages that do not require JavaScript interactions to load their content. Disabling JavaScript behaviors avoids automated scrolling, clicks, and AJAX requests, resulting in faster captures.
* Avoid **capture\_outlinks=1** unless you need to archive all discovered outlinks. If you only need specific outlinks, first capture the target page, review the outlinks returned by SPN2, and then submit capture requests only for the URLs you want to archive.

# Limitations {#limitations}

SPN2 is subject to a number of operational limits designed to ensure service performance, reliability and fair resource usage. The current limits are summarized in the table below..

| Limitation | Description |
| :---- | :---- |
| Network connection timeout \= 10s | If the target URL does not respond within 10 seconds, the server is considered unresponsive and the capture fails. |
| Max captures per minute for authenticated users \= 7 and for anonymous users \= 3\. | Any user can do N captures per minute. Exceeding these limits results in an error. |
| Max web page capture time \= 50s | The SPN2 browser can spend up to 50s loading a URL and running JS behaviors. If the process does not complete within this window, it is terminated. Partial success may still be recorded if sufficient content has been captured. |
| Max capture duration \= 2m | The total time spent capturing any URL cannot be over 2m. |
| Max JS behavior runtime \= 7s (configurable) | The total time running JS events (scroll down, mouse over, etc) cannot be over 5s by default. |
| Max redirects \= 3 | Up to 3 HTTP redirects are followed automatically during capture. |
| Max resource size \= 2GB | The max file size SPN2 can download. |
| Max number of outlinks captured using capture\_outlinks option \= 100 | SPN2 captures the first N outlinks automatically when using option capture\_outlinks. Outlinks are ordered using some rules before selecting the first N: PDF Epub URLs containing substrings "new" or "update" URLs of the same domain as the original capture URL. Please note that if you don’t use option capture\_outlinks, you get a list of all outlinks without any filtering or ranking. You could use that list to download any URLs necessary. |
| Max number of outlinks returned \= 500 | SPN2 just returns a list of outlinks if "capture outlinks" is not selected. This list is limited to 500 items. |
| Max number of embeds returned \= 500 | SPN2 tracks all captured embeds and lists them in "resources". This list is limited to 500 items. |
| Max number of links captured from emails in [spn@archive.org](mailto:spn@archive.org) \= 300 | SPN2 tries to capture the first 300 links in emails sent to [spn@archive.org](mailto:spn@archive.org).  |
| Max captures per day for anonymous users \= 200 | Anonymous users can use SPN2 but their total captures per day cannot be more than this limit. |
| Max captures per day for authenticated users \= 30k | The captures of authenticated users cannot be more than this limit per day. If you need to make more captures, please contact [info@archive.org](mailto:info@archive.org).  |
| Max captures per day for a URL \= 5 | It is possible to capture the same URL only 5 times per day. |
| Blocked URLs | SPN2 uses Mozilla web tracker block lists to avoid capturing some URLs. You may get an "error:blocked-url" when trying to make a capture. |
| Artificial delays for multiple concurrent captures on the same host. | When more than 20 concurrent captures target the same host, additional requests are delayed to avoid overloading the target and blocking SPN2. The delay algorithm is: When concurrent\_capture\_number \> 20 for the same host, delay concurrent\_capture\_number/5 sec. For example: if concurrent\_capture\_number \= 50, delay a new capture by 50/5 \= 10 sec. |
| Max emails processed by [spn@archive.org](mailto:spn@archive.org) service per user per day= 10 | You can send HTML emails with links to capture at [spn@archive.org](mailto:spn@archive.org). The service processes up to 10 emails per user per day and discards the rest. |
| Max screenshot size is 4MB | If you select "Save screen shot" and its size is \> 4MB, it is skipped to avoid system overload. |
| Max captures’ size per day is 2GB for anonymous users. | Anonymous Patrons are limited to 500MB total captured data per day. |
| Max captures’ size per day is 5GB for authenticated users. | Authenticated Patrons are limited to 5GB total captured data per day. |

# Example PHP script using the SPN2 API to capture a URL {#example-php-script-using-the-spn2-api-to-capture-a-url}

| \<?php /\*\*  \* Example PHP script which captures a URL via the SPN2 API.  \* Note that this script doesn't include proper exception handling and is not  \* optimised for production use.  \* Tested with PHP 7.0 and the PHP curl extension on Ubuntu 16.04.  \*  \* Full SPN2 API reference:  \* https://docs.google.com/document/d/1Nsv52MvSjbLb2PCpHlat0gkzw0EvtSgpKHu4mk0MnrA/edit  \*  \* Archive.org credentials are required to use the SPN2 API,  \* get your credentials from https://archive.org/account/s3.php  \*/ $KEY \= "XXX"; $SECRET \= "YYY"; $TARGET\_URL \= "https://bbc.co.uk"; $headers \= array("Accept: application/json",                  "Content-Type: application/x-www-form-urlencoded;charset=UTF-8",                  "Authorization: LOW {$KEY}:{$SECRET}"); $params \= array('url'=\>$TARGET\_URL); $ch \= curl\_init(); curl\_setopt($ch, CURLOPT\_URL, "https://web.archive.org/save"); curl\_setopt($ch, CURLOPT\_POST, 1); curl\_setopt($ch, CURLOPT\_POSTFIELDS, http\_build\_query($params)); curl\_setopt($ch, CURLOPT\_HTTPHEADER, $headers); curl\_setopt($ch, CURLOPT\_RETURNTRANSFER, true); $response \= curl\_exec($ch); curl\_close($ch); $data \= json\_decode($response, true); $job\_id \= $data\['job\_id'\]; print("Capture started, job id: {$job\_id}\\n"); while(true) {     sleep(5);     $response \= file\_get\_contents("http://web.archive.org/save/status/{$job\_id}");     $data \= json\_decode($response, true);     if ($data\['status'\] \== 'success') {         print("Capture complete: https://web.archive.org/web/{$data\['timestamp'\]}/{$data\['original\_url'\]}\\n");         break;     } else if ($data\['status'\] \== 'error') {         print("Error: {$data\['message'\]}\\n");         break;     }     print("Wait, still capturing...\\n"); } |
| :---- |

# Frequently Asked Questions {#frequently-asked-questions}

**Q1. I can access the page [http://example.com/](http://example.com/) from my browser but SPN2 returns error: "Live page is not available".**

Before starting a capture, SPN2 performs a quick HTTP HEAD and if that fails an HTTP GET to see if the target URL is online. If both requests fail, SPN2 returns the error: *"Live page is not available"*.
Successful checks are cached for 10 minutes to improve performance for subsequent requests.

However, this check may be inaccurate for several reasons:

1. **IP-based blocking:** The site may have blocked requests from IA IPs in general.
2. **Traffic overload/throttling:** High concurrent capture activity (from other users or outlink expansion) may cause the target server or firewall to rate-limit or block SPN2 requests. In such cases, the site may still be accessible from a normal browser but not from SPN2. To reduce this risk, SPN2 applies delays when there are 50+ concurrent captures targeting the same host.
3. **Transient server issues:** Sites are often temporarily unavailable due to outages, network issues or server-side instability.

**Q2. I’m trying to capture a web page that contains a lot of links using the "capture outlinks" option but no outlinks are captured.**

SPN2 can extract outlinks from many file types: HTML pages, PDF, RSS, XML, epub and JSON files. For each format, it uses a dedicated extraction pipeline. For HTML pages, it’s a JS script that extracts URLs from a\[href\], area\[href\], a\[onclick\], a\[ondblclick\]: [https://github.com/internetarchive/brozzler/blob/master/brozzler/js-templates/extract-outlinks.js](https://github.com/internetarchive/brozzler/blob/master/brozzler/js-templates/extract-outlinks.js)

Outlink extraction may fail or return no results due to the following conditions:

* **Timeout during extraction:** Outlink processing did not complete within the 30-second extraction window.
* **Overall capture timeout:** The full capture exceeded the 90-second limit, leaving insufficient time to run outlink extraction.
* **Unsupported or inaccessible link formats:** Links may be embedded in non-standard attributes, dynamically generated via obfuscated JavaScript, or stored in encrypted/unsupported formats (e.g., encrypted PDFs).

**Q3. Why do I see *"Your capture will begin in XXs.".* Is SPN2 overloaded?**

When we run more than 20 concurrent captures on the same host, we introduce an artificial delay on subsequent captures to avoid overloading the target and blocking SPN2. The delay algorithm is:

When concurrent\_capture\_number \> 20 for the same host, delay concurrent\_capture\_number/5 sec.
For example: if concurrent\_capture\_number \= 50, delay a new capture by 50/5 \= 10 sec.

By "concurrent captures", we mean captures performed in the last 60 sec.

In addition to that, if a target site returns HTTP status=429 (too many requests), we delay any subsequent captures for 10 to 20 sec. This rule applies for 60 sec after receiving the status=429 response.