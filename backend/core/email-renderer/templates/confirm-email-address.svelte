<script>
  // Props that can be passed to this template
  export let code = "000000";
  export let username = "";
  export let darkMode = false;
  export let lang = "en";
  export let t = (key, vars) => key; // This will be provided by the renderer
  
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
    <title>{t('email.confirm_your_email.text', {})}</title>
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
          {t('email.confirm_your_email.text', {})}
        </h1>
        
        <p style="margin-bottom: 16px;">
          {username ? t('email.confirm.greetingWithName', { username }) : t('email.confirm.greeting', {})}
        </p>
        
        <p style="margin-bottom: 16px;">
          {t('email.confirm.instruction', {})}
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
          {t('email.confirm.expiration', {})}
        </p>
        
        <hr style="
          border: none;
          border-top: 1px solid {darkMode ? '#333333' : '#e0e0e0'};
          margin: 24px 0;
        " />
        
        <p style="font-size: 12px; color: {darkMode ? '#909090' : '#666666'}; text-align: center;">
          {t('email.confirm.footer', {})}
        </p>
      </div>
      
      <div style="text-align: center; margin-top: 24px; font-size: 12px; color: {darkMode ? '#707070' : '#999999'};">
        © {new Date().getFullYear()} OpenMates
      </div>
    </div>
  </body>
</html>
