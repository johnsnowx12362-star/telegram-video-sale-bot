# Telegram Video Sale Bot

Starter bot for lawful, allowed/non-adult digital videos.

Features:
- /start with Get Video, Balance, Add Balance
- Razorpay Payment Link converted to a QR
- Razorpay webhook signature verification
- Automatic balance credit after payment_link.paid
- SQLite balance/payment/video database
- Video delivery using Telegram file_id

Setup:
1. Create a Telegram bot with @BotFather.
2. Put credentials in a .env file based on .env.example.
3. Install: pip install -r requirements.txt
4. Run: python bot.py
5. Your server needs a public HTTPS URL for the Razorpay webhook:
   https://YOUR-DOMAIN/razorpay/webhook
6. In Razorpay, subscribe the webhook to payment_link.paid.

Important:
- Never publish BOT_TOKEN, RAZORPAY_KEY_SECRET, or the webhook secret.
- Use Razorpay Test Mode while developing; use Live keys only after your account is activated.
- A Telegram bot cannot silently force-add a user to an arbitrary group. Use an invite/join-request link after verified payment.
- The sample does not include an admin command for uploading videos; videos can be inserted using their Telegram file_id. An admin panel can be added next.
