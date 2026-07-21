"""Turnstile solver for nodriver."""
import asyncio
import nodriver as uc


async def solve_turnstile(page, timeout: int = 60) -> str | None:
    """
    Wait for Turnstile to auto-solve or solve via CDP-level interaction.

    Args:
        page: nodriver Tab instance
        timeout: max seconds to wait for token

    Returns:
        Turnstile token if solved, None otherwise
    """
    try:
        import time
        start = time.time()

        # Poll for token (Turnstile may auto-solve on good fingerprint/proxy)
        while time.time() - start < timeout:
            token = await page.evaluate(
                "document.querySelector('input[name=cf-turnstile-response]')?.value || ''"
            )
            if token and len(token) > 20:
                return token

            # Try verify_cf() once after 5s if still no token
            if time.time() - start > 5 and time.time() - start < 7:
                try:
                    await page.verify_cf()
                except Exception:
                    pass  # verify_cf() may fail, continue polling

            await asyncio.sleep(1)

        return None

    except Exception as e:
        print(f"Turnstile solve error: {e}")
        return None
