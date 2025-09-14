from datetime import datetime
from sys import stderr
from time import sleep
from traceback import format_exc
from argparse import ArgumentParser
from prometheus_client import start_http_server, Gauge
import requests
from pydantic import BaseModel, field_validator
import logfire

API_BASE = "https://govuk-display-screen-20e334eeb1ba.herokuapp.com/"
verbosity = 0
enable_logfire = False


def error(msg: str):
    if enable_logfire:
        logfire.error(msg)
    else:
        print(msg, file=stderr, flush=True)


def warn(msg: str):
    if enable_logfire:
        logfire.warning(msg)
    else:
        print(msg, flush=True)


def info(msg: str):
    if enable_logfire:
        logfire.info(msg)
    else:
        print(msg, flush=True)


def debug(msg: str):
    if enable_logfire:
        logfire.debug(msg)
    elif verbosity:
        print(msg)


def fetch_active_users():
    response = requests.get(f"{API_BASE}/active-users")
    response.raise_for_status()
    data = response.json()
    if "active_users_30_minutes" not in data:
        raise ValueError(
            f'Expected "active_users_30_minutes" key in API response: {data}'
        )
    return data["active_users_30_minutes"]


class PopularPage(BaseModel):
    page_views: int
    page_path: str
    page_title: str

    # Converts pretty-printed (formatted) numbers into normal ints
    @field_validator("page_views", mode="before")
    def parse_page_views(cls, value):
        if isinstance(value, str):
            return int(value.replace(",", ""))
        return value


def fetch_popular_content():
    response = requests.get(f"{API_BASE}/popular-content")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(
            f"Expected a list from the popular content API, received a {type(data)}"
        )
    return [PopularPage.model_validate(item) for item in data]


def main():
    parser = ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=9050,
        help="the port to run the Prometheus exporter on",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        help="log whenever data is scraped",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="how often to fetch data, in seconds",
    )
    parser.add_argument(
        "--logfire-token",
        type=str,
        help="a Logfire token for sending logs to the cloud",
    )
    args = parser.parse_args()
    global verbosity, enable_logfire
    verbosity = args.verbose
    enable_logfire = bool(args.logfire_token)

    if enable_logfire:
        logfire.configure()
        logfire.instrument_pydantic()

    start_http_server(args.port)
    info(f"Started metrics exporter: http://localhost:{args.port}/metrics")

    has_had_success = False
    active_users_gauge = Gauge(
        "active_users_30_minutes", "Number of users on GOV.UK in the last 30 minutes"
    )
    page_views_gauge = Gauge(
        "popular_page_views",
        "Number of page views for the top 10 most popular pages on GOV.UK",
        ["page_path", "page_title"],
    )

    while True:
        if not args.interval:
            # Only run at the end of the minute, because that's when GOV.UK reports the most accurate active user stats
            if not (56 <= datetime.now().second < 60):
                sleep(1)
                continue
        try:
            active_users = fetch_active_users()
            popular_pages = fetch_popular_content()
            active_users_gauge.set(active_users)
            for page in popular_pages:
                page_views_gauge.labels(
                    page_path=page.page_path, page_title=page.page_title
                ).set(page.page_views)
            debug(
                f"Successfully fetched data ({len(popular_pages)} popular pages, active_users={active_users})"
            )
            has_had_success = True
        except Exception as e:
            # Exit the program if the first fetch fails
            if not has_had_success:
                raise e
            error(f"Failed to fetch data: {format_exc()}")
        finally:
            if args.interval:
                sleep(args.interval)
            else:
                sleep(55)  # close to 1 minute, but with a bit of margin for inaccuracy


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
