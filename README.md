# UniFi Parent

UniFi Parent is a hybrid parental control application that bridges the gap between **Pi-hole** (for DNS telemetry/tracking) and **UniFi** (for network enforcement). It monitors how much time specific devices spend on designated websites and automatically blocks their internet access (or specific traffic rules) when their daily time limit is reached.

## 🚀 Quick Setup Guide

Assuming you have already deployed the Docker container and validated your Pi-hole and UniFi connections in the **Settings** tab, follow these steps to get everything running:

### 1. Create Domain Categories
Categories define the group of websites you want to monitor and limit.
* Navigate to the **Settings** tab.
* Scroll down to **Domain Categories**.
* Add a new category (e.g., `YouTube`).
* Enter the domains separated by commas (e.g., `youtube.com, googlevideo.com, ytimg.com`).
* Click **Add Category**.

### 2. Create a Child Profile
A Profile represents a specific device on your network (like a child's iPad or PC).
* Go to the **Dashboard** and click **Add Profile**.
* **Name**: The child's name or device name.
* **IP Address**: The local IP of the device (used to track queries in Pi-hole). *Tip: Set a static/fixed IP for this device in your UniFi controller!*
* **MAC Address**: The MAC address of the device (used by UniFi to block the device if needed).
* **Curfew**: (Optional) Set a hard start and end time where the device is blocked regardless of usage.

### 3. Assign Daily Time Limits (Quotas)
Once the profile is created, you need to assign it a quota for the categories you created.
* On the Dashboard, find the Profile you just created.
* Under the profile, select a **Category** from the dropdown.
* Enter the **Daily Limit** in minutes (e.g., `60` for 1 hour).
* **UniFi Traffic Rule ID (Optional)**: 
  * If you leave this blank, hitting the time limit will completely block the device's MAC address from the network.
  * If you want to block *only* the app (e.g., only block YouTube but leave Wikipedia working), you must first create an "App Group" Traffic Rule in your UniFi Network app, leave it paused/disabled, find its ID using the UniFi API, and paste it here. *(For beginners, leaving it blank is much easier!)*
* Click **Add Limit**.

## 📊 How it Works (The Background Process)

Every few minutes, the background scheduler runs:
1. **Reads Pi-hole:** It asks your Pi-hole(s) for the last few minutes of DNS queries.
2. **Matches IP to Profile:** It looks for queries originating from the IP addresses in your Profiles.
3. **Matches Domain to Category:** It checks if the requested domain matches any of your Categories.
4. **Calculates Active Minutes:** If a match is found, it adds an "active minute" to that Profile's daily quota.
5. **Enforces Limits:** If the active minutes exceed the daily limit, it immediately contacts the UniFi Controller and blocks the device's MAC address (or enables the specific traffic rule).

## 🛠️ Manual Overrides

Sometimes a device is blocked, but you want to grant an extension or fix a mistake.
* **Reset Usage:** On the Dashboard, click the "Reset" button next to a quota. This resets their active minutes to 0 for the day and automatically unblocks them in UniFi.
* **Lift Station Block:** If a device is completely blocked by MAC address, click the "Unblock Station" button on their Profile card to force UniFi to unblock them.
