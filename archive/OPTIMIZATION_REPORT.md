
# Optimization Report

This report details the performance bottlenecks identified in the `hippique-orchestrator` pipeline, the optimizations applied, and the expected performance gains.

## 1. Identified Bottlenecks

The primary performance bottleneck was the web scraping process located in the `online_fetch_zeturf.py` module. The original implementation used the Selenium library to control a web browser in a synchronous manner. This approach had several drawbacks:

*   **High Latency**: Starting a browser instance for each race is resource-intensive and slow.
*   **No Parallelism**: Races were scraped sequentially, making the total scraping time proportional to the number of races.
*   **Lack of Resilience**: The original implementation had no mechanism to handle transient network errors, leading to failures.

## 2. Optimizations Applied

To address these issues, the following optimizations were implemented:

*   **Asynchronous Scraping**: The Selenium-based scraper was completely replaced with a new implementation based on `httpx` and `asyncio`. This allows the application to make multiple HTTP requests concurrently, significantly reducing the total scraping time when fetching data for multiple races.
*   **Improved Resilience**: The `tenacity` library was integrated to add a retry mechanism with exponential backoff to the HTTP requests. This makes the scraper more resilient to transient network errors (e.g., timeouts, 5xx errors).
*   **Data Validation**: Pydantic models were introduced in a new `src/schemas.py` file. These models (`Runner`, `RaceSnapshot`, `NormalizedRaceSnapshot`) are used to validate the structure and data types of the information scraped from the website. This improves the overall robustness of the pipeline by ensuring that downstream components receive data in the expected format.

## 3. Performance Gains

The implemented optimizations are expected to yield significant performance improvements.

*   **Scraping Time**: The time required to scrape multiple races is expected to be drastically reduced. For example, scraping 3 races, which would have taken approximately 45 seconds with the old implementation (assuming an average of 15 seconds per race), should now take around **8-10 seconds**. The requests are now performed in parallel, so the total time is close to the time of the single longest request.
*   **Resource Usage**: The `httpx`-based approach is much more lightweight than Selenium, as it does not require a full web browser to be instantiated. This leads to lower CPU and memory consumption.

These optimizations transform the scraping process from a major bottleneck into a fast and resilient data source for the pipeline.
