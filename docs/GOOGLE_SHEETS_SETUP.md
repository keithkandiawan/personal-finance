# Google Sheets API Setup Guide

This guide walks you through setting up Google Sheets API access for the sheet balance import script.

## Overview

We'll use a **Service Account** to access Google Sheets. This allows the script to read your sheet without OAuth prompts.

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Create Project**
3. Name it: `personal-finance-tracker`
4. Click **Create**

## Step 2: Enable Google Sheets API

1. In your project, go to **APIs & Services** → **Library**
2. Search for "Google Sheets API"
3. Click on it and press **Enable**

## Step 3: Create Service Account

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **Service Account**
3. Fill in:
   - **Name**: `portfolio-tracker`
   - **Description**: `Service account for reading sheet balances`
4. Click **Create and Continue**
5. Skip the optional steps (click **Done**)

## Step 4: Generate Credentials JSON

1. In **APIs & Services** → **Credentials**, find your service account
2. Click on the service account email
3. Go to **Keys** tab
4. Click **Add Key** → **Create new key**
5. Choose **JSON** format
6. Click **Create**
7. A JSON file will download - this is your credentials file!

## Step 5: Save Credentials

1. Rename the downloaded file to `google_credentials.json`
2. Move it to your project:
   ```bash
   mv ~/Downloads/your-project-*.json /path/to/personal-finance/google_credentials.json
   ```
3. Secure the file:
   ```bash
   chmod 600 google_credentials.json
   ```
4. **Important**: This file contains secrets! Never commit it to git (it's already in .gitignore)

## Step 6: Share Google Sheet with Service Account

1. Open the `google_credentials.json` file
2. Find the `client_email` field - it looks like:
   ```
   portfolio-tracker@personal-finance-tracker-xxxxx.iam.gserviceaccount.com
   ```
3. Copy this email address
4. Open your Google Sheet (sheet balances)
5. Click **Share** button
6. Paste the service account email
7. Set permission to **Viewer** (read-only is enough)
8. Click **Send**

## Step 7: Get Sheet ID and Range

Your Google Sheets URL looks like:
```
https://docs.google.com/spreadsheets/d/1ABC...XYZ/edit
                                        ^^^^^^^^
                                        This is the Sheet ID
```

**Sheet ID**: The long string in the URL (e.g., `1ABC...XYZ`)

**Range**: The tab name and cell range (e.g., `Sheet Balances!A2:C`)
- `Sheet Balances` = tab name
- `A2:C` = from row 2 (skip header) to end, columns A-C

## Step 8: Configure Environment

Create a `.env` file in your project root:

```bash
# Google Sheets Configuration
GOOGLE_CREDENTIALS_PATH=google_credentials.json
GOOGLE_SHEET_ID=your-sheet-id-here
GOOGLE_SHEET_RANGE=Sheet Balances!A2:C
```

Example:
```bash
GOOGLE_CREDENTIALS_PATH=google_credentials.json
GOOGLE_SHEET_ID=1ABCdefGHI_jklMNOpqrSTUvwxYZ0123456789
GOOGLE_SHEET_RANGE=Sheet Balances!A2:C
```

## Step 9: Install Python Dependencies

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dotenv
```

Or with the project:
```bash
pip install -e .
```

## Step 10: Test Connection

```bash
python scripts/test_sheets_connection.py
```

This will verify:
- Credentials are valid
- Sheet is accessible
- Data can be read

---

## Troubleshooting

### "Permission denied" error
- Make sure you shared the sheet with the service account email
- Check that the service account has Viewer permission

### "Sheet not found" error
- Verify the Sheet ID is correct
- Check that the tab name in GOOGLE_SHEET_RANGE matches your sheet

### "Invalid credentials" error
- Ensure google_credentials.json is in the correct location
- Verify the file has proper permissions (chmod 600)

### "API not enabled" error
- Go back to Step 2 and enable Google Sheets API

---

## Security Notes

✅ **Safe**:
- Service account credentials in project root (gitignored)
- Read-only access to specific sheet
- No OAuth tokens to manage

❌ **Never**:
- Commit google_credentials.json to git
- Share credentials publicly
- Give Editor permission (Viewer is enough)

---

## Sheet Structure

Your Google Sheet should have this structure:

| Account | Currency | Amount |
|---------|----------|--------|
| bca_checking | IDR | 50000000 |
| binance_main | USDT | 1000 |
| friend_loan | IDR | -5000000 |

**Important**:
- **Account names** must match accounts in your database
- **Currency codes** must exist in currencies table
- **Amount** can be positive (assets) or negative (liabilities)
- Header row (row 1) is skipped automatically

---

## Next Steps

Once setup is complete, you can run:

```bash
python scripts/ingest_balances.py --sources sheet
```

This will:
1. Read current balances from Google Sheet
2. Create snapshot with current timestamp
3. Calculate USD/IDR values using fx_rates
4. Insert into balances table

---

## Export Sheet Setup (Optional)

If you want analytics exported to a **separate** Google Sheet for dashboards:

### Step 1: Create Export Sheet

1. Go to [Google Sheets](https://sheets.google.com/)
2. Click **Blank** to create a new spreadsheet
3. Rename it: `Portfolio Analytics` (or any name you prefer)
4. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/EXPORT_SHEET_ID_HERE/edit
   ```

### Step 2: Share with Service Account

1. Open the `google_credentials.json` file
2. Copy the `client_email` (same as import sheet)
3. Open your **export** Google Sheet
4. Click **Share** button
5. Paste the service account email
6. Set permission to **Editor** (not Viewer - export requires write access)
7. Click **Send**

### Step 3: Configure Environment

Add to your `.env` file:

```bash
# Add this line (keep existing GOOGLE_SHEET_ID for imports)
EXPORT_SHEET_ID=your-export-sheet-id-here
```

Example:
```bash
GOOGLE_CREDENTIALS_PATH=google_credentials.json
GOOGLE_SHEET_ID=1ABCdef...        # Import sheet (balance ingestion)
EXPORT_SHEET_ID=1XYZ123...        # Export sheet (analytics)
```

### Step 4: Run First Export

```bash
python scripts/export_to_sheets.py
```

This automatically creates 4 tabs:
- **Summary** - Assets, Liabilities, Net Worth totals
- **By Asset Class** - Breakdown by crypto/stocks/fiat
- **By Currency** - Holdings per currency
- **History** - Daily net worth time series

### Step 5: Create Charts (Optional)

You can now create charts in Google Sheets referencing these tabs:

**Chart Best Practices:**
- Use **unbounded ranges**: `History!A2:C` (not `A2:C100`)
- This allows charts to grow as history accumulates
- Charts are preserved when data is overwritten
- Example chart types:
  - **Line chart** for History tab (net worth over time)
  - **Pie chart** for By Asset Class tab (allocation)
  - **Bar chart** for By Currency tab (top holdings)

### Troubleshooting

**"Permission denied" error:**
- Make sure service account has **Editor** permission (not Viewer)
- Export requires write access to create/update tabs

**"Sheet not found" error:**
- Verify `EXPORT_SHEET_ID` in `.env` file
- Check that Sheet ID matches the URL

**Charts disappeared:**
- This shouldn't happen - script uses `.clear()` which preserves charts
- If charts are deleted, recreate them and ensure you're using unbounded ranges

**Numbers not formatted:**
- Script formats with 2 decimals and commas automatically
- For currency symbols, use Google Sheets: Format → Number → Currency
