"""Command-line interface for the polite crawler."""

import asyncio
from typing import List, Optional

import click

from polite_crawler.crawler import Crawler, CrawlerConfig, CrawlResult
from polite_crawler.database import Database


def get_db_url(db_path: Optional[str] = None) -> str:
    """Get the database URL from the db path.

    Args:
        db_path: Path to the database file.

    Returns:
        Database URL string.
    """
    if db_path:
        return f"sqlite+aiosqlite:///{db_path}"
    return "sqlite+aiosqlite:///crawler.db"


def print_result(result: CrawlResult) -> None:
    """Print a crawl result to the console.

    Args:
        result: The CrawlResult to print.
    """
    if result.success:
        click.echo(
            click.style(f"✓ SUCCESS", fg="green")
            + f" {result.url}"
            + (f" (status: {result.status_code})" if result.status_code else "")
        )
    else:
        click.echo(
            click.style(f"✗ FAILED", fg="red")
            + f" {result.url}"
            + (f" - {result.error}" if result.error else "")
        )


async def run_crawl(
    urls: List[str],
    db_path: Optional[str],
    max_concurrency: int,
    rate_limit: float,
    max_retries: int,
    verbose: bool,
) -> int:
    """Run the crawl asynchronously.

    Args:
        urls: List of URLs to crawl.
        db_path: Path to the database file.
        max_concurrency: Maximum number of concurrent requests.
        rate_limit: Requests per second limit.
        max_retries: Maximum number of retries per URL.
        verbose: Whether to show verbose output.

    Returns:
        Exit code (0 for success, 1 if any failures).
    """
    db_url = get_db_url(db_path)
    db = Database(db_url)
    
    config = CrawlerConfig(
        max_concurrency=max_concurrency,
        rate_limit=rate_limit,
        max_attempts=max_retries,
    )
    
    crawler = Crawler(config=config, database=db)
    
    try:
        await crawler.init()
        
        click.echo(f"Starting crawl of {len(urls)} URL(s)...")
        click.echo(f"  Max concurrency: {max_concurrency}")
        click.echo(f"  Rate limit: {rate_limit} req/s")
        click.echo(f"  Max retries: {max_retries}")
        click.echo(f"  Database: {db_url}")
        click.echo("")
        
        success_count = 0
        total_count = len(urls)
        
        def on_progress(url: str, result: CrawlResult) -> None:
            nonlocal success_count
            if result.success:
                success_count += 1
            print_result(result)
            if verbose and result.content:
                preview = result.content[:200]
                click.echo(f"  Content preview: {preview!r}")
        
        results = await crawler.crawl_urls(
            urls=urls,
            max_retries=max_retries,
            on_progress=on_progress,
        )
        
        click.echo("")
        click.echo("=" * 50)
        click.echo("Crawl Summary:")
        click.echo(f"  Total URLs: {total_count}")
        click.echo(f"  Success: {success_count}")
        click.echo(f"  Failed: {total_count - success_count}")
        
        stats = await crawler.get_stats()
        click.echo(f"  Database stats: {stats}")
        
        return 0 if success_count == total_count else 1
        
    finally:
        await crawler.close()


async def run_stats(
    db_path: Optional[str],
) -> None:
    """Show crawl statistics.

    Args:
        db_path: Path to the database file.
    """
    db_url = get_db_url(db_path)
    db = Database(db_url)
    
    try:
        await db.init_db()
        stats = await db.get_stats()
        
        click.echo("Crawler Statistics:")
        click.echo(f"  Database: {db_url}")
        click.echo("")
        click.echo(f"  Total URLs: {stats['total']}")
        click.echo(f"  Pending: {stats['pending']}")
        click.echo(f"  In Progress: {stats['in_progress']}")
        click.echo(click.style(f"  Success: {stats['success']}", fg="green"))
        click.echo(click.style(f"  Failed: {stats['failed']}", fg="red"))
        
    finally:
        await db.close()


@click.group()
@click.version_option()
def main():
    """Polite Crawler - A rate-limited web crawler with persistence.

    \b
    Features:
    - Concurrent crawling
    - Global rate limiting
    - Automatic retry on failure
    - URL persistence with SQLite
    """
    pass


@main.command("crawl")
@click.argument("urls", nargs=-1, required=True)
@click.option(
    "--db",
    "-d",
    type=click.Path(),
    help="Path to the database file (default: crawler.db)",
)
@click.option(
    "--concurrency",
    "-c",
    type=int,
    default=10,
    help="Maximum concurrent requests (default: 10)",
)
@click.option(
    "--rate-limit",
    "-r",
    type=float,
    default=10.0,
    help="Requests per second (default: 10.0)",
)
@click.option(
    "--max-retries",
    "-R",
    type=int,
    default=3,
    help="Maximum retries per URL (default: 3)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show verbose output",
)
def crawl(
    urls: List[str],
    db: Optional[str],
    concurrency: int,
    rate_limit: float,
    max_retries: int,
    verbose: bool,
):
    """Crawl one or more URLs.

    \b
    Example:
      polite-crawler crawl https://example.com https://google.com
      polite-crawler crawl https://example.com --db mydb.db -c 5 -r 2.0
    """
    exit_code = asyncio.run(
        run_crawl(
            urls=list(urls),
            db_path=db,
            max_concurrency=concurrency,
            rate_limit=rate_limit,
            max_retries=max_retries,
            verbose=verbose,
        )
    )
    raise SystemExit(exit_code)


@main.command("stats")
@click.option(
    "--db",
    "-d",
    type=click.Path(),
    help="Path to the database file (default: crawler.db)",
)
def stats(db: Optional[str]):
    """Show crawl statistics from the database.

    \b
    Example:
      polite-crawler stats
      polite-crawler stats --db mydb.db
    """
    asyncio.run(run_stats(db_path=db))


if __name__ == "__main__":
    main()
