"""Address helpers shared by classification, rules and recruitment records."""

# Personal mailbox providers: a sender here says nothing about the organization they work for.
FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
        "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com", "gmx.com",
    }
)


def domain_of(address: str) -> str:
    return address.rpartition("@")[2].lower()


def business_domain(address: str) -> str | None:
    """The sender's organization domain, or None for personal mailbox providers."""
    domain = domain_of(address)
    return None if not domain or domain in FREE_MAIL_DOMAINS else domain
