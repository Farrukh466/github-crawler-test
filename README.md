# **GitHub Repository Crawler**

This project contains an automated data pipeline designed to collect repository data from the GitHub GraphQL API. The system is built to be robust, efficient, and scalable, incorporating best practices in software and data engineering.

The pipeline is orchestrated via GitHub Actions and performs the following steps:

1. Sets up a clean, containerized PostgreSQL database.  
2. Installs all necessary dependencies.  
3. Creates the required database schema and tables.  
4. Executes the main crawler script, which fetches 100,000 unique repositories by intelligently querying the GitHub API in chunks to overcome its search limitations.  
5. Handles rate limits, network errors, and API data inconsistencies gracefully.  
6. Dumps the final, clean data from the database into a CSV file.  
7. Uploads the resulting CSV as a downloadable artifact.

## **Scaling to 500 Million Repositories**

Scaling the data collection from 100,000 to 500 million repositories requires a fundamental architectural shift from a single-script process to a distributed, massively parallel system. The current approach would be too slow and fragile. Here is what I would do differently:

1. **Implement a Distributed Task Queue System:**  
   * **Technique:** I would use a robust task queue system like **Celery with RabbitMQ**. A central "dispatcher" script would generate thousands of small, specific jobs (e.g., "fetch repos for created:2024-01-15") and push them onto the queue. Dozens of independent "worker" machines would then execute these tasks in parallel.  
   * **Benefit:** This provides massive horizontal scalability. If the process is too slow, we simply add more worker machines.  
2. **Decouple Data Collection from Data Loading (ETL):**  
   * **Technique:** The workers' sole responsibility would be to fetch raw JSON data and dump it into a scalable cloud storage bucket like **Amazon S3**. A separate, independent process (e.g., using Apache Spark) would then read these files, transform the data, and use a highly efficient bulk-loading method to insert it into the database.  
   * **Benefit:** This separation makes the system more resilient. If the database loading fails, we can simply retry that step without having to re-run the expensive API crawl.  
3. **Redesign the Database for Scale:**  
   * **Technique:** I would use a managed database service like **Amazon RDS** and implement PostgreSQL's native **table partitioning**, likely partitioning by a hash of the repository id.  
   * **Benefit:** Partitioning breaks the single 500-million-row table into hundreds of smaller physical sub-tables. This dramatically improves indexing, write performance, and query speed.  
4. **Implement a Resilient State Management Layer:**  
   * **Technique:** I would use a fast in-memory database like **Redis** to store the real-time state of every job (e.g., PENDING, RUNNING, COMPLETE, FAILED).  
   * **Benefit:** If the entire system restarts, the dispatcher can read from Redis to know exactly where to pick up, skipping completed jobs and requeueing failed ones. This ensures no data is lost and no work is repeated during a crawl that could take days or weeks.

## **Evolving the Database Schema**

To gather more complex metadata like issues, pull requests, and comments, the schema must evolve from a single table to a **normalized, multi-table relational model**. This design is key to maintaining efficiency, especially for data that changes frequently.

The principle is to give each type of data its own dedicated table and connect them using foreign keys.

1. repositories Table (The Central Hub):  
   This table remains the same, containing core repository information.  
   * id (Primary Key), nameWithOwner, stargazerCount  
2. pull\_requests and issues Tables:  
   These tables would store information specific to PRs and issues, respectively.  
   * id (Primary Key), title, state, author  
   * **repository\_id (Foreign Key)** \-\> This links each PR or issue back to its parent repository.  
3. comments Table (The Key to Efficiency):  
   This table is designed to handle frequently added data like comments.  
   * id (Primary Key), body, author  
   * **pull\_request\_id (Foreign Key, Nullable)** \-\> Links a comment to a PR.  
   * **issue\_id (Foreign Key, Nullable)** \-\> Links a comment to an issue.

#### **How This Achieves Efficient Updates**

This design perfectly handles the scenario: **"A PR can get 10 comments today and then 20 comments tomorrow."**

* **The Operation:** When the 20 new comments are found, the script would perform 20 simple **INSERT** operations into the comments table.  
* **The Efficiency ("Minimal Rows Affected"):**  
  * The pull\_requests table is **never touched or updated**.  
  * The number of rows affected is exactly 20—one for each new piece of data.  
  * This append-only approach is extremely fast and avoids expensive updates on large tables.

This normalized model is highly scalable. Adding new metadata like **Reviews** or **CI Checks** would simply involve creating new, specialized tables that link back to the appropriate parent table, following the same efficient, insert-focused pattern.