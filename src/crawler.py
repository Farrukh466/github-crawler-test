import os
import time
import requests
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from datetime import date, timedelta

# Load environment variables from a .env file for local development.
# In GitHub Actions, these are provided directly in the workflow file.
load_dotenv()

# --- Configuration ---
GITHUB_API_URL = 'https://api.github.com/graphql'
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'postgres')
DB_USER = os.getenv('DB_USER', 'postgres')
# Default password for local testing. This is overridden in the GitHub Actions environment.
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT', '5432')

# --- GraphQL Query Template ---
# This is a template for our API requests. The '%s' is a placeholder
# that we will fill with a specific search query for each chunk.
QUERY_TEMPLATE = """
query($after: String) {
  rateLimit {
    remaining
    resetAt
  }
  search(query: "%s", type: REPOSITORY, first: 100, after: $after) {
    nodes {
      ... on Repository {
        id
        nameWithOwner
        stargazerCount
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""

def fetch_repos_for_query(search_query, limit_per_query=1000):
    """
    Fetches up to 1000 unique repositories for a single, specific search query.
    Uses a dictionary to automatically de-duplicate any duplicate results returned by the API.
    """
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set. Please check your .env file or environment variables.")
        
    headers = {'Authorization': f'bearer {GITHUB_TOKEN}'}
    repos_dict = {}
    has_next_page = True
    after_cursor = None
    
    # We format the QUERY_TEMPLATE with the specific search_query for this chunk.
    formatted_query = QUERY_TEMPLATE % search_query
    
    print(f"\n--- Starting new chunk for query: '{search_query}' ---")
    
    while has_next_page and len(repos_dict) < limit_per_query:
        variables = {'after': after_cursor}
        try:
            response = requests.post(
                GITHUB_API_URL,
                json={'query': formatted_query, 'variables': variables},
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error fetching data: {e}. Retrying in 15 seconds...")
            time.sleep(15)
            continue

        data = response.json()
        
        if 'errors' in data:
            print(f"GraphQL errors: {data['errors']}")
            break

        search_results = data['data']['search']
        
        new_nodes = search_results.get('nodes', [])
        for repo_node in new_nodes:
            # Ensure the node is valid and contains an ID before processing
            if repo_node and 'id' in repo_node:
                repo_id = repo_node['id']
                # Using a dictionary automatically handles duplicates from the API
                repos_dict[repo_id] = (
                    repo_id, 
                    repo_node.get('nameWithOwner'), 
                    repo_node.get('stargazerCount')
                )

        page_info = search_results['pageInfo']
        has_next_page = page_info['hasNextPage']
        after_cursor = page_info['endCursor']
        
        rate_limit = data['data'].get('rateLimit', {})
        remaining = rate_limit.get('remaining', 100)
        
        if len(repos_dict) % 200 == 0 and len(repos_dict) > 0:
             print(f"   ... collected {len(repos_dict)} for this chunk.")

    print(f"--- Finished chunk. Collected {len(repos_dict)} unique repos. Rate limit at {remaining}. ---")
    return repos_dict

def store_in_db(repositories):
    """
    Stores data in the PostgreSQL database using an efficient UPSERT operation.
    """
    if not repositories:
        print("No repositories to store.")
        return

    insert_query = """
    INSERT INTO github_data.repositories (id, name, stargazer_count)
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
      stargazer_count = EXCLUDED.stargazer_count,
      crawled_at = NOW();
    """
    
    conn = None
    try:
        print("\nConnecting to the database...")
        conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT)
        with conn.cursor() as cur:
            # Use execute_values for efficient bulk insertion.
            execute_values(cur, insert_query, repositories, template=None, page_size=500)
            conn.commit()
            print(f"Successfully inserted/updated {len(repositories)} records in the database.")
    except psycopg2.Error as e:
        print(f"Database error: {e}")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    TARGET_COUNT = 100000
    all_repos_dict = {}
    query_chunks = []
    
    # Generate a list of date ranges to create different query "chunks".
    # This allows us to overcome the API's ~1000 result limit per query.
    start_date = date.today()
    for i in range(120): # Generate enough chunks to be sure we can find 100k repos
        end_date = start_date - timedelta(days=1)
        start_date = end_date - timedelta(days=30)
        # Create a query string for repos created in this 30-day window
        date_range_query = f"is:public created:{start_date.strftime('%Y-%m-%d')}..{end_date.strftime('%Y-%m-%d')}"
        query_chunks.append(date_range_query)

    # Main loop to run queries until the target is met.
    for query in query_chunks:
        chunk_dict = fetch_repos_for_query(query)
        # Merges new data, overwriting duplicates from previous chunks to keep data fresh.
        all_repos_dict.update(chunk_dict)
        
        print(f"\n>>>> TOTAL UNIQUE REPOS COLLECTED SO FAR: {len(all_repos_dict)} / {TARGET_COUNT} <<<<")
        
        if len(all_repos_dict) >= TARGET_COUNT:
            print("\nTarget of 100,000 repositories reached. Stopping crawl.")
            break
            
    # Convert the final dictionary of unique repos into a list of tuples for the database.
    final_repos_list = list(all_repos_dict.values())
    
    # Trim the list to exactly the target count if we over-collected.
    if len(final_repos_list) > TARGET_COUNT:
        final_repos_list = final_repos_list[:TARGET_COUNT]

    print(f"\nCrawl complete. Total unique repositories to be stored: {len(final_repos_list)}")
    
    store_in_db(final_repos_list)

