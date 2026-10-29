# Reflection

## What assumptions did I make?

Since the portal had no proper documentation, I assumed all timestamps were in Indian Standard Time (IST) because the network is in Jaipur. I treated `kwh` and `kvah` as cumulative readings and calculated consumption using the difference between consecutive readings. I also assumed the 403 exported records were complete, empty hierarchy codes meant missing values, and `/portal/dts` was the main source for transformer names. Since readings stopped on 30 June 2026, I assumed the data was a fixed snapshot and used a 10-minute cache, although I did not verify this over time.

## Which part was the most difficult, and how did I get unstuck?

The bulk export was the most difficult part. Directly calling the endpoint did not work, so I checked the browser's Network tab and found the `keys` request and the `x-timestamp` and `x-signature` headers. I searched the loaded JavaScript files to understand how the portal generated its HMAC-SHA256 signature. After verifying it against a captured request, I implemented the process in Python and tested different failure cases.

## If I had another day, what would I improve?

I would test the client using actual portal responses instead of only manually created data. I would also analyse all 403 meters for unusual readings and improve the `/quality` endpoint. Other improvements would include background data refresh, persistent shared caching, and a web interface with a map and consumption charts.

## What mistake did I make while solving this?

My main mistake was assuming the login failure was caused by my code when I had entered the wrong password. I also discovered that the portal returned HTTP 200 even when login failed, so checking the response body was necessary. I faced indentation errors while copying code and accidentally shared screenshots containing a session cookie and signing secret. These mistakes taught me to check inputs carefully and handle sensitive information more securely.

## If I were reviewing my own submission, what would I criticise?

Some data-cleaning rules are based on assumptions that need further testing. I tested 403 records and only nine energy samples, so the results may not cover every case. The hierarchy-matching logic may also produce incorrect results when the match is unclear. Additionally, the cache is temporary and per-process, the API lacks authentication, and the client runs synchronously. My tests use synthetic data rather than actual portal responses. I also used AI for guidance and parts of the code, as disclosed in the README, so I need to ensure I understand the implementation well enough to explain my decisions.