# Crypto Exchange API Setup Guide

This guide shows you how to create **read-only** API keys for fetching your crypto balances.

## ⚠️ Security First

**CRITICAL:**
- ✅ **Create READ-ONLY keys** - Never enable trading/withdrawal permissions
- ✅ **Restrict IP** - Bind keys to your server IP if possible
- ✅ **Store securely** - Keep keys in `.env` file (chmod 600)
- ❌ **Never commit** - `.env` is gitignored, never push to GitHub
- ❌ **Never share** - These keys access your account

## Binance API Setup

### Step 1: Create API Key

1. Log in to [Binance](https://www.binance.com/)
2. Go to **Profile** → **API Management**
3. Click **Create API**
4. Choose **System Generated** API Key
5. Label: `Portfolio Tracker - Read Only`
6. Complete 2FA verification

### Step 2: Configure Permissions

**Enable:**
- ✅ **Enable Reading** (spot account)

**Disable (CRITICAL):**
- ❌ Enable Spot & Margin Trading
- ❌ Enable Withdrawals
- ❌ Enable Futures

### Step 3: (Optional) Restrict IP

- Click **Edit restrictions**
- Select **Restrict access to trusted IPs only**
- Add your server/home IP address

### Step 4: Copy Credentials

- **API Key**: Copy and save
- **Secret Key**: Copy and save (shown only once!)

### Step 5: Add to .env

```bash
BINANCE_API_KEY=your-actual-api-key-here
BINANCE_API_SECRET=your-actual-secret-key-here
```

---

## OKX API Setup

### Step 1: Create API Key

1. Log in to [OKX](https://www.okx.com/)
2. Go to **Profile** → **API**
3. Click **Create V5 API key**
4. Complete verification

### Step 2: Configure Permissions

**Select:**
- ✅ **Read** only

**DO NOT select:**
- ❌ Trade
- ❌ Withdraw

### Step 3: Set API Passphrase

- Create a strong passphrase (different from login password)
- Save it securely - you'll need it for the script

### Step 4: (Optional) IP Restriction

- Choose **Bind to specific IP**
- Add your server/home IP

### Step 5: Copy Credentials

- **API Key**: Copy
- **Secret Key**: Copy
- **Passphrase**: The one you just created

### Step 6: Add to .env

```bash
OKX_API_KEY=your-okx-api-key
OKX_API_SECRET=your-okx-secret
OKX_API_PASSWORD=your-okx-passphrase
```

---

## Bitget API Setup

### Step 1: Create API Key

1. Log in to [Bitget](https://www.bitget.com/)
2. Go to **Account** → **API Management**
3. Click **Create API**
4. Choose API type: **Spot**

### Step 2: Configure Permissions

**Enable:**
- ✅ **Read** only

**Disable:**
- ❌ Trade
- ❌ Transfer
- ❌ Withdraw

### Step 3: Set Passphrase

- Create API passphrase
- Save it - you'll need it for configuration

### Step 4: (Optional) IP Whitelist

- Enable IP whitelist
- Add your server IP

### Step 5: Copy Credentials

- **API Key**: Copy
- **Secret Key**: Copy
- **Passphrase**: The one you created

### Step 6: Add to .env

```bash
BITGET_API_KEY=your-bitget-api-key
BITGET_API_SECRET=your-bitget-secret
BITGET_API_PASSWORD=your-bitget-passphrase
```

---

## Verify Setup

### Test Connection

```bash
# Install dependencies first
pip install -e .

# Test the script (dry run)
python scripts/ingest_balances.py --sources exchanges
```

### Expected Output

```
2025-12-27 12:00:00 - INFO - Crypto Balance Ingestion - Starting
2025-12-27 12:00:00 - INFO - Configured exchanges: Binance, OKX, Bitget Evelyn
2025-12-27 12:00:01 - INFO - Fetching from Binance...
2025-12-27 12:00:01 - INFO -   Binance spot: 5 currencies
2025-12-27 12:00:01 - INFO -   Binance funding: 2 currencies
2025-12-27 12:00:01 - INFO - Binance total: 7 currencies across all accounts
2025-12-27 12:00:02 - INFO - ✓ Binance: Fetched 7 balances
2025-12-27 12:00:02 - INFO - Fetching from OKX...
2025-12-27 12:00:02 - INFO -   OKX trading: 3 currencies
2025-12-27 12:00:02 - INFO - OKX total: 3 currencies across all accounts
2025-12-27 12:00:02 - INFO - ✓ OKX: Fetched 3 balances
2025-12-27 12:00:03 - INFO - Fetching from Bitget Evelyn...
2025-12-27 12:00:03 - INFO -   Bitget spot: 2 currencies
2025-12-27 12:00:03 - INFO - Bitget total: 2 currencies across all accounts
2025-12-27 12:00:03 - INFO - ✓ Bitget Evelyn: Fetched 2 balances
2025-12-27 12:00:03 - INFO - ✓ Successfully imported 12 crypto balances
```

Note: The script automatically fetches from all available account types (spot, margin, futures, funding, earn) and aggregates balances by currency.

---

## Troubleshooting

### "Invalid API Key" Error

**Check:**
- API key copied correctly (no extra spaces)
- Secret key copied correctly
- Passphrase correct (OKX/Bitget)

### "IP Restricted" Error

**Solutions:**
- Add your current IP to whitelist
- Or disable IP restriction (less secure)
- Check your public IP: `curl ifconfig.me`

### "Permission Denied" Error

**Check:**
- API has "Read" permission enabled
- You're accessing the right account type (spot/trading)

### "Account Not Found" Error

**Check:**
- Account name in database matches exactly:
  - `Binance` (not `binance` or `Binance Main`)
  - `OKX` (not `okx`)
  - `Bitget Evelyn` (not `Bitget`)
- Run: `sqlite3 data/portfolio.db "SELECT name FROM accounts WHERE type = (SELECT id FROM account_types WHERE name='exchange')"`

---

## Security Best Practices

1. **Read-only keys only** - Never enable trading/withdrawal
2. **IP restrictions** - Lock to your server IP when possible
3. **Rotate keys** - Change keys every 90 days
4. **Monitor usage** - Check API logs on exchange for suspicious activity
5. **Separate keys** - Use different keys for different purposes
6. **Secure storage** - Keep `.env` file permissions at 600:
   ```bash
   chmod 600 .env
   ```

---

## Partial Configuration

You don't need to configure all exchanges. The script will only fetch from exchanges with API keys configured:

```bash
# Only Binance configured
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
# OKX and Bitget keys commented out or removed
```

Script output:
```
Configured exchanges: Binance
✓ Binance: Fetched 5 balances
```

---

## Next Steps

Once API keys are configured:

1. **Test manually:**
   ```bash
   python scripts/ingest_balances.py --sources exchanges
   ```

2. **Check balances:**
   ```bash
   sqlite3 data/portfolio.db "SELECT account_name, currency_code, quantity FROM latest_balances WHERE account_id IN (SELECT id FROM accounts WHERE type = (SELECT id FROM account_types WHERE name='exchange'))"
   ```

3. **Schedule automation:**
   ```bash
   # Add to crontab (every 4 hours)
   0 */4 * * * cd /path/to/personal-finance && python scripts/ingest_balances.py --sources exchanges >> logs/exchanges.log 2>&1
   ```
