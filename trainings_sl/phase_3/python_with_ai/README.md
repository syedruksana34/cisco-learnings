# Standalone Gemini Chat

This app is separate from the employee management system.

1. From this directory, install dependencies:

   ```sh
   python -m pip install -r requirements.txt
   ```

2. Create a Gemini API key at https://aistudio.google.com/apikey and add it to
   `.env` as `GEMINI_API_KEY=your-key`. The file is ignored by Git; do not share
   your key or put it in frontend code. Optionally set `GEMINI_MODEL` in `.env`
   to an available model (the default is `gemini-3.5-flash`).

3. Start the server from this directory:

   ```sh
   uvicorn main:app --host 127.0.0.1 --port 8001
   ```

4. Open http://127.0.0.1:8001. Gemini requests are subject to your Google AI
   Studio project's available quota and billing. Messages in a conversation
   are sent to Gemini; don't include information you don't want to share.
