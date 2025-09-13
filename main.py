from sys import stderr
from time import sleep
from traceback import format_exc
from argparse import ArgumentParser
from prometheus_client import start_http_server, Gauge
import requests
from pydantic import BaseModel, field_validator

API_BASE = "https://govuk-display-screen-20e334eeb1ba.herokuapp.com/"


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
        default=5,
        help="how often to fetch data, in seconds",
    )
    args = parser.parse_args()

    if False:
        import logfire

        logfire.configure()
        logfire.instrument_pydantic()

    start_http_server(args.port)
    print(f"Started metrics exporter: http://localhost:{args.port}/metrics", flush=True)

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
        try:
            active_users_gauge.set(fetch_active_users())
            for page in fetch_popular_content():
                page_views_gauge.labels(
                    page_path=page.page_path, page_title=page.page_title
                ).set(page.page_views)
            if args.verbose:
                print(f"Successfully fetched data")
            has_had_success = True
        except Exception as e:
            # Exit the program if the first fetch fails
            if not has_had_success:
                raise e
            print(f"Failed to fetch data: {format_exc()}", file=stderr, flush=True)
        finally:
            sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
