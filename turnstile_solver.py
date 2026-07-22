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

        # Wait for Turnstile iframe to fully load first
        print("→ waiting for Turnstile iframe...")
        iframe_loaded = False
        for _ in range(10):  # Max 10s wait for iframe
            iframe_ready = await page.evaluate('''(() => {
                const iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
                if (!iframe) return false;
                // Check if iframe is loaded and has dimensions
                return iframe.contentWindow && iframe.offsetHeight > 0;
            })()''')
            if iframe_ready:
                iframe_loaded = True
                print("✓ Turnstile iframe loaded")
                break
            await asyncio.sleep(1)

        if not iframe_loaded:
            print("✗ Turnstile iframe not ready")
            return None

        # Give challenge 3s to render after iframe loads
        await asyncio.sleep(3)

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
