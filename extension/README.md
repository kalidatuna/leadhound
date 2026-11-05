# leadhound browser extension

Found a client post or a business website while browsing? Send it to leadhound in one click.

- **Save this page as a lead**: opens leadhound with the link, title and any text you selected filled in.
  leadhound scores it and writes a first message like any other lead.
- **Check this website**: opens the website check with the address filled in.

It only talks to leadhound on your own computer (`http://127.0.0.1:8787` by default; change the port in the popup
if leadhound runs on another one). You confirm everything inside leadhound. It reads the current tab only when you
click a button (`activeTab`), and the selected text only to fill the form.

## Install (Chrome, Edge, Brave, Opera)

1. Download this folder (or the whole repository) and unzip it.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and pick this `extension` folder.

## Install (Firefox)

Open `about:debugging#/runtime/this-firefox`, click **Load Temporary Add-on…** and pick `manifest.json`.
Firefox removes temporary add-ons when it restarts until the extension is published on addons.mozilla.org.
