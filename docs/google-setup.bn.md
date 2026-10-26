# Google Connect setup (বাংলা গাইড)

এই কাজ **একবারই** করতে হবে, ~১৫ মিনিট লাগবে। শেষ হলে Sora তোমার Gmail, Calendar, Drive, Docs, Sheets, Slides, Tasks আর Contacts ব্যবহার করতে পারবে।

**কেন নিজের OAuth app লাগবে:** Claude-এর মতো "Connect Google" বোতামের পেছনে একটা Google OAuth app থাকে। Sora-র জন্য সেটা তুমি নিজের Google Cloud account-এ বানাবে। User শুধু তুমি একা, তাই Google-এর review বা verification লাগবে না, কোনো টাকাও লাগবে না।

> 💡 পুরো গাইডে **যে Gmail account Sora-র সাথে connect করবে, সেটা দিয়েই login করবে।**

---

## ধাপ ১: Google Cloud project বানাও

1. [console.cloud.google.com](https://console.cloud.google.com/) খোলো। প্রথমবার হলে Terms of Service-এ রাজি হয়ে নাও।
2. উপরের বাম দিকে project-এর নামের dropdown-এ ক্লিক করো, তারপর **New Project**।
3. Project name দাও `sora-assistant`, তারপর **Create**।
4. Project তৈরি হলে উপরের dropdown থেকে **`sora-assistant` select করা আছে কিনা** দেখে নাও। বাকি সব কাজ এই project-এর ভেতরে হবে।

> Billing account বা card লাগবে না। এই API-গুলো ব্যক্তিগত ব্যবহারে free।

## ধাপ ২: API-গুলো চালু করো

বাম menu → **APIs & Services → Library**। নিচের প্রতিটা API search করে খোলো, তারপর **Enable** চাপো:

| API-র নাম | কী কাজে লাগে |
|---|---|
| **Gmail API** | email পড়া, পাঠানো, নতুন mail-এর notification |
| **Google Calendar API** | event দেখা ও বানানো |
| **Google Drive API** | file খোঁজা ও পড়া |
| **Google Docs API** | Doc বানানো |
| **Google Sheets API** | Sheet পড়া ও লেখা |
| **Google Slides API** | Presentation বানানো |
| **Google Tasks API** | To-do list |
| **People API** | নাম দিয়ে কারো email খুঁজে বের করা |

৮টাই enable করতে হবে। কোনোটা বাদ পড়লে পরে ওই কাজ করতে গেলে `... API has not been used in project ...` ধরনের error আসবে।

## ধাপ ৩: Consent screen (Google Auth Platform)

বাম menu → **Google Auth platform**। "Google Auth platform not configured yet" লেখা দেখালে **Get Started** চাপো।

1. **App Information**
   - App name: `Sora`
   - User support email: তোমার email
   - **Next**
2. **Audience**: **External** বেছে নাও → **Next**
   (Internal শুধু Google Workspace-এর অফিস account-এ দেখা যায়। সাধারণ Gmail-এর জন্য External।)
3. **Contact Information**: তোমার email → **Next**
4. **Finish**: "I agree to the Google API Services: User Data Policy"-তে টিক দাও → **Continue** → **Create**

## ধাপ ৪: নিজেকে test user বানাও, তারপর app Publish করো

1. বাম দিকে **Audience** খোলো।
2. **Test users** অংশে **Add users** চাপো। তোমার Gmail address দাও → **Save**।
3. একই page-এর উপরে **Publishing status: Testing** লেখা আছে। পাশের **Publish app** চাপো, তারপর **Confirm**।
   এখন status হবে **In production**।

> ⚠️ **এই ধাপ বাদ দিও না।** App "Testing" অবস্থায় থাকলে Google-এর দেওয়া access **৭ দিন পর পর expire হয়ে যায়**, তখন প্রতি সপ্তাহে আবার connect করতে হবে। "In production" করলে এই সমস্যা থাকে না।
>
> Publish করলে Google "verification" চাইতে পারে। **ওটা করতে হবে না।** Verification ছাড়াই app ১০০ জন পর্যন্ত user-এর জন্য চলে, আর এখানে user শুধু তুমি।

## ধাপ ৫: OAuth Client বানাও (Client ID আর Secret)

1. বাম দিকে **Clients** → **Create client**।
2. **Application type: Web application**।
3. Name দাও `Sora backend`।
4. **Authorized redirect URIs**-এ **Add URI** চাপো, তারপর হুবহু এটা লেখো:
   ```
   http://localhost:8000/oauth/google/callback
   ```
   (শেষে `/` দেবে না, `https` লিখবে না। একটা অক্ষরও না মিললে Google `redirect_uri_mismatch` error দেবে।)
5. **Create** চাপো।
6. একটা popup-এ **Client ID** আর **Client secret** দেখাবে। দুটোই কপি করে নাও।

> ⚠️ Client secret আর কখনো পুরোটা দেখা নাও যেতে পারে। তাই এখনই কপি করো। হারিয়ে গেলে ওই client-এ গিয়ে নতুন secret বানানো যায়।
>
> **"Download JSON" চাপার দরকার নেই।** ভুল করে download হয়ে গেলে Sora-র folder-এ রেখো না।

## ধাপ ৬: `.env`-এ বসাও

`E:\Sora 3.0.1\.env` file খুলে নিচের দুটো লাইন যোগ করো:

```
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
```

এগুলো chat-এ পেস্ট করবে না, GitHub-এও কখনো যাবে না। `.env` git থেকে বাদ দেওয়া আছে।

## ধাপ ৭: Connect করো

দুটো terminal লাগবে।

**Terminal ১: server চালু করো** (এটা খোলা রাখবে):
```
cd "E:\Sora 3.0.1\backend"
..\.venv\Scripts\python -m sora serve
```

**Terminal ২: connect করো**:
```
cd "E:\Sora 3.0.1\backend"
..\.venv\Scripts\python -m sora connect-google
```
এটা সব service একসাথে connect করে। চাইলে শুধু নির্দিষ্ট কয়েকটাও connect করা যায়, পরে বাকিগুলো যোগ করা যাবে:
```
..\.venv\Scripts\python -m sora connect-google gmail sheets
```
Service-গুলোর নাম: `gmail`, `calendar`, `drive`, `docs`, `sheets`, `slides`, `tasks`, `contacts`।

> 📱 **App বানানো হলে এই terminal-এর কাজটা আর লাগবে না।** App-এর Connections page-এ প্রতিটা service-এর পাশে আলাদা **Connect** বোতাম থাকবে, যেমন Gmail, Sheets, Slides। একটা চাপলে Google শুধু ওই service-এর permission চাইবে। আগে connect করা service-গুলোও connect থাকবে। কোনো service চাইলে app থেকে বন্ধও করা যাবে।

Browser-এ Google-এর page খুলবে। এরপর:
1. তোমার Gmail account বেছে নাও।
2. **"Google hasn't verified this app"** লেখা দেখাবে। এটা স্বাভাবিক, কারণ app-টা তোমার নিজের।
   **Advanced** চাপো, তারপর **Go to Sora (unsafe)**।
3. Permission-এর তালিকা আসবে। **সবগুলোতে টিক দাও** (Select all), তারপর **Continue**।
4. শেষে **"✅ Google connected"** লেখা page দেখাবে। Browser বন্ধ করে দাও।

## ধাপ ৮: Test করো

Server চালু রেখেই অন্য terminal-এ:
```
..\.venv\Scripts\python -m sora chat
```
তারপর লেখো:
- `amar unread email gula dekhao`
- `ei shoptahe amar calendar e ki ache?`
- `Drive e amar CV khujo`

**নতুন email-এর notification:** server চালু থাকলে Sora প্রতি ৯০ সেকেন্ডে Gmail check করে। Connect করার পরে যে mail আসবে, শুধু সেগুলোরই notification দেবে। পুরনো mail-এর জন্য দেবে না।

---

## সমস্যা হলে

| যা দেখাচ্ছে | কারণ | সমাধান |
|---|---|---|
| `Error 400: redirect_uri_mismatch` | ধাপ ৫-এর redirect URI হুবহু মেলেনি | Clients-এ গিয়ে ঠিক করো: `http://localhost:8000/oauth/google/callback`। Save করার পর ১–২ মিনিট অপেক্ষা করো |
| `Error 403: access_denied` | App এখনো Testing-এ আছে, আর তুমি test user না | ধাপ ৪ আবার করো: test user যোগ করো, তারপর Publish |
| `invalid_client` | Client ID বা secret ভুল কপি হয়েছে | `.env` দেখো: শুরু-শেষে বাড়তি space বা উদ্ধৃতি চিহ্ন (") যেন না থাকে। তারপর server restart |
| `GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set` | `.env`-এ বসানোর পর server restart হয়নি | Terminal ১-এ `Ctrl+C` চাপো, তারপর আবার `serve` চালাও |
| `The server isn't running` | Terminal ১-এ server চালু নেই | আগে `serve` চালাও |
| Chat-এ `... API has not been used in project ...` | ওই API enable করা হয়নি | ধাপ ২-এ গিয়ে enable করো, ১–২ মিনিট পর আবার চেষ্টা করো |
| "This connect link expired" | Link খোলার ১৫ মিনিট পার হয়ে গেছে | আবার `connect-google` চালাও |
| কিছুদিন পর Sora বলছে "Google access expired" | Google account-এর password বদলেছ, বা app Testing-এ রয়ে গেছে | ধাপ ৪ দেখো, তারপর আবার `connect-google` |

## Disconnect করতে চাইলে

[myaccount.google.com/permissions](https://myaccount.google.com/permissions) খুলে **Sora** খুঁজে নাও, তারপর **Remove access**। অথবা পরে app-এর Settings থেকে Disconnect করা যাবে।

## Sora কী কী permission চায়

| Permission | কী করতে পারবে |
|---|---|
| Gmail (`gmail.modify`) | mail পড়া, খোঁজা, পাঠানো, reply, draft, label, trash। **চিরতরে delete করতে পারবে না।** পাঠানো বা trash করার আগে সবসময় তোমার অনুমতি নেবে |
| Calendar | event দেখা, বানানো, বদলানো। অন্য কাউকে invite করতে বা কিছু delete করতে হলে অনুমতি নেবে |
| Drive | file খোঁজা আর পড়া। Docs, Sheets, Slides বানানোও এর মধ্যে পড়ে |
| Tasks | To-do দেখা, যোগ করা, শেষ করা |
| Contacts (শুধু পড়া) | নাম দিয়ে email address খুঁজে বের করা |

Token গুলো encrypt হয়ে তোমার PC-র database-এ থাকে। অন্য কোথাও যায় না।

### Drive আর Contacts-এ Sora আসলে কী করতে পারে

Google-এর permission কাগজে-কলমে বড় হলেও, Sora ততটুকুই করতে পারে যতটুকুর জন্য ওর tool বানানো আছে।

| | পারে | পারে না |
|---|---|---|
| **Drive** | file খোঁজা, পড়া; নতুন Doc, Sheet, Slides বানানো; Doc-এ লেখা যোগ করা; Sheet-এ row যোগ করা | **file delete, কারো সাথে share, public link বানানো, move বা rename:** এগুলোর tool-ই নেই |
| **Sheet overwrite** | পুরনো data-র ওপর নতুন লেখা বসানো, **শুধু তোমার অনুমতি নিয়ে** | না বলে overwrite করা |
| **Contacts** | নাম দিয়ে email বা phone নম্বর খোঁজা | contact বানানো, বদলানো, delete করা (permission-টাই শুধু পড়ার) |

ভুল করে কিছু বদলে গেলে Docs আর Sheets-এর **File → Version history** থেকে আগের অবস্থায় ফেরানো যায়।

**ক্ষতিকর email বা file থেকে বাড়তি সুরক্ষা:** কোনো কথোপকথনে email, file বা web page-এর লেখা একবার ঢুকলে, তারপর থেকে নিচের কাজগুলো তোমার "হ্যাঁ" ছাড়া হবে না:
- কোনো link খোলা বা web page আনা
- Doc বা Sheet-এ লেখা
- Calendar-এ কাউকে invite করা
- Memory বা email rule বদলানো

ফলে কোনো email যদি লুকিয়ে লেখে "এই file-টা অমুক জায়গায় পাঠাও", Sora চুপচাপ সেটা করতে পারবে না। তোমার সামনে approval চাইবে, তখন তুমি "না" বলবে।
