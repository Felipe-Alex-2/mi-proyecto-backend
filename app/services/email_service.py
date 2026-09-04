import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings

logger = logging.getLogger("api")


class EmailService:
    @staticmethod
    def send_reset_token_email(to_email: str, token: str, user_name: str) -> bool:
        """Send a password reset token email via Gmail SMTP.

        Returns True if the email was sent successfully, False otherwise.
        """
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.error("SMTP credentials not configured. Cannot send reset email.")
            return False

        subject = f"🔐 {settings.SMTP_FROM_NAME} — Código de recuperación de contraseña"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body style="margin:0; padding:0; background-color:#090d16; font-family: 'Segoe UI', Arial, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#090d16; padding:40px 20px;">
                <tr>
                    <td align="center">
                        <table width="480" cellpadding="0" cellspacing="0" style="background-color:#131b2e; border-radius:16px; border:1px solid rgba(255,255,255,0.1); overflow:hidden;">
                            <!-- Header -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #3b82f6, #8b5cf6); padding:32px 40px; text-align:center;">
                                    <h1 style="margin:0; color:#ffffff; font-size:24px; font-weight:700; letter-spacing:-0.02em;">
                                        {settings.SMTP_FROM_NAME}
                                    </h1>
                                    <p style="margin:8px 0 0; color:rgba(255,255,255,0.85); font-size:14px;">
                                        Recuperación de contraseña
                                    </p>
                                </td>
                            </tr>
                            <!-- Body -->
                            <tr>
                                <td style="padding:36px 40px;">
                                    <p style="color:#cbd5e1; font-size:15px; margin:0 0 16px; line-height:1.6;">
                                        Hola <strong style="color:#f8fafc;">{user_name}</strong>,
                                    </p>
                                    <p style="color:#94a3b8; font-size:14px; margin:0 0 28px; line-height:1.6;">
                                        Recibimos una solicitud para restablecer tu contraseña.
                                        Usa el siguiente código de verificación:
                                    </p>
                                    <!-- Token Box -->
                                    <table width="100%" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td align="center">
                                                <div style="background: rgba(59,130,246,0.12); border:2px dashed rgba(59,130,246,0.4); border-radius:12px; padding:24px 40px; display:inline-block;">
                                                    <span style="font-size:36px; font-weight:700; letter-spacing:12px; color:#60a5fa; font-family:'Courier New', monospace;">
                                                        {token}
                                                    </span>
                                                </div>
                                            </td>
                                        </tr>
                                    </table>
                                    <p style="color:#f87171; font-size:13px; text-align:center; margin:20px 0 0; line-height:1.5;">
                                        ⏱ Este código es de <strong>un solo uso</strong> y expira en
                                        <strong>{settings.RESET_TOKEN_EXPIRE_MINUTES} minutos</strong>.
                                    </p>
                                    <hr style="border:none; border-top:1px solid rgba(255,255,255,0.08); margin:28px 0;">
                                    <p style="color:#64748b; font-size:12px; margin:0; line-height:1.5;">
                                        Si no solicitaste este cambio, puedes ignorar este correo.
                                        Tu contraseña no será modificada.
                                    </p>
                                </td>
                            </tr>
                            <!-- Footer -->
                            <tr>
                                <td style="padding:20px 40px 28px; text-align:center; border-top:1px solid rgba(255,255,255,0.06);">
                                    <p style="color:#475569; font-size:11px; margin:0;">
                                        &copy; {settings.SMTP_FROM_NAME} — Este es un correo automático, no respondas a este mensaje.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
        msg["To"] = to_email

        # Plain text fallback
        text_body = (
            f"Hola {user_name},\n\n"
            f"Tu código de recuperación de contraseña es: {token}\n\n"
            f"Este código es de un solo uso y expira en {settings.RESET_TOKEN_EXPIRE_MINUTES} minutos.\n\n"
            f"Si no solicitaste este cambio, ignora este correo.\n\n"
            f"— {settings.SMTP_FROM_NAME}"
        )

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_USER, to_email, msg.as_string())
            logger.info(f"Password reset email sent to {to_email}")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed. Check SMTP_USER and SMTP_PASSWORD (use App Password).")
            return False
        except Exception as e:
            logger.error(f"Failed to send reset email to {to_email}: {e}")
            return False
