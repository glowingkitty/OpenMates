<script>
  // Props that can be passed to this template
  export let code = "000000";
  export let username = "";
  export let darkMode = false;
  export let lang = "en";
  
  // Language-specific text
  const texts = {
    en: {
      title: "Confirm Your Email Address",
      greeting: username ? `Hello ${username},` : "Hello,",
      instruction: "Please confirm your email address by entering this code in the app:",
      expiration: "This code will expire in 30 minutes.",
      footer: "If you didn't request this email, you can safely ignore it."
    },
    de: {
      title: "Bestätigen Sie Ihre E-Mail-Adresse",
      greeting: username ? `Hallo ${username},` : "Hallo,",
      instruction: "Bitte bestätigen Sie Ihre E-Mail-Adresse, indem Sie diesen Code in der App eingeben:",
      expiration: "Dieser Code läuft in 30 Minuten ab.",
      footer: "Wenn Sie diese E-Mail nicht angefordert haben, können Sie sie ignorieren."
    }
  };
  
  // Get text in selected language or fall back to English
  const t = texts[lang] || texts.en;
  
  // Set colors based on dark mode
  const colors = {
    background: darkMode ? "#121212" : "#ffffff",
    text: darkMode ? "#e0e0e0" : "#333333",
    accent: "#4f46e5", // Indigo accent color
    codeBackground: darkMode ? "#2d2d2d" : "#f3f4f6",
    codeBorder: darkMode ? "#3f3f3f" : "#d1d5db"
  };
</script>

<html lang={lang}>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{t.title}</title>
  </head>
  <body style="
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 0;
    background-color: {colors.background};
    color: {colors.text};
    line-height: 1.6;
  ">
    <div style="
      max-width: 600px;
      margin: 0 auto;
      padding: 20px;
    ">
      <div style="text-align: center; margin-bottom: 32px; padding-top: 20px;">
        <img src="https://openmates.io/logo.png" alt="OpenMates Logo" style="height: 60px;" />
      </div>
      
      <div style="
        border-radius: 8px;
        padding: 20px;
        background-color: {colors.background};
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      ">
        <h1 style="color: {colors.accent}; text-align: center; font-size: 24px; margin-bottom: 24px;">
          {t.title}
        </h1>
        
        <p style="margin-bottom: 16px;">
          {t.greeting}
        </p>
        
        <p style="margin-bottom: 16px;">
          {t.instruction}
        </p>
        
        <div style="
          background-color: {colors.codeBackground};
          border: 1px solid {colors.codeBorder};
          border-radius: 6px;
          padding: 16px;
          margin: 24px 0;
          text-align: center;
          font-family: monospace;
          font-size: 24px;
          letter-spacing: 4px;
          font-weight: bold;
        ">
          {code}
        </div>
        
        <p style="font-size: 14px; color: {darkMode ? '#909090' : '#666666'};">
          {t.expiration}
        </p>
        
        <hr style="
          border: none;
          border-top: 1px solid {darkMode ? '#333333' : '#e0e0e0'};
          margin: 24px 0;
        " />
        
        <p style="font-size: 12px; color: {darkMode ? '#909090' : '#666666'}; text-align: center;">
          {t.footer}
        </p>
      </div>
      
      <div style="text-align: center; margin-top: 24px; font-size: 12px; color: {darkMode ? '#707070' : '#999999'};">
        © {new Date().getFullYear()} OpenMates
      </div>
    </div>
  </body>
</html>
