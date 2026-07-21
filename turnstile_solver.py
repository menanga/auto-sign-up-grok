"""Turnstile solver for nodriver."""
import asyncio
import nodriver as uc


async def solve_turnstile(page, timeout: int = 40) -> str | None:
    """
    Solve Cloudflare Turnstile challenge using nodriver's built-in bypass.

    Args:
        page: nodriver Tab instance
        timeout: max seconds to wait

    Returns:
        Turnstile token if solved, None otherwise
    """
    try:
        # Wait for turnstile iframe to appear
        await asyncio.sleep(2)

        # Use nodriver's built-in Cloudflare bypass
        solved = await page.verify_cf(timeout=timeout)

        if not solved:
            return None

        # Extract token from hidden input
        await asyncio.sleep(1)
        token = await page.evaluate(
            "document.querySelector('input[name=cf-turnstile-response]')?.value || ''"
        )

        return token if token else None

    except Exception as e:
        print(f"Turnstile solve error: {e}")
        return None
