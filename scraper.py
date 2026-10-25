import os
import time
import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Configuration
BASE_URL = "https://escapepod.org/category/podcasts/"
OUTPUT_DIR = "downloaded_stories"
RUN_FILE = "RUN"              # Sentinel file for graceful shutdown
DELAY_BETWEEN_REQUESTS = 1.5  # Seconds to sleep between requests to be polite
USER_AGENT = "EscapePodScraper/1.0 (+https://github.com/your-username/escapepod-scraper; Python scraper for personal archive/learning)"

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Initialize requests session
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

def clean_filename(title):
    """Convert title to a safe filename."""
    title = re.sub(r'[\\/*?:"<>|]', "", title)
    title = title.replace(" ", "_").lower()
    return title[:100]  # Limit length

def clean_story_paragraphs(p_tags):
    """
    Cleans up paragraphs by removing leading show notes (names and their links)
    and trailing generic outro/promotional/copyright boilerplates.
    """
    temp_paras = [p.get_text(strip=True) for p in p_tags if p.get_text(strip=True)]
    
    # Trim from the end if we hit host commentary or other metadata blocks
    for idx, text in enumerate(temp_paras):
        if any(stop_word in text.lower() for stop_word in [
            "host commentary", 
            "commentary by", 
            "about the author", 
            "about the narrator"
        ]):
            temp_paras = temp_paras[:idx]
            break
            
    # Filter leading credits (show notes / metadata links at the top)
    i = 0
    n = len(temp_paras)
    start_idx = 0
    while i < n:
        text = temp_paras[i]
        
        # Check if the current paragraph is a URL
        is_url = text.startswith("http://") or text.startswith("https://") or ".com/" in text or ".org/" in text
        
        # Check if it is a short line (e.g. name of narrator/author)
        is_short = len(text) < 80
        
        # Check if the next line is a URL
        next_is_url = False
        if i + 1 < n:
            next_text = temp_paras[i+1]
            next_is_url = next_text.startswith("http://") or next_text.startswith("https://") or ".com/" in next_text or ".org/" in next_text
            
        # If it is a URL, or it is short and followed by a URL, skip it
        if is_url or (is_short and next_is_url):
            i += 1
            continue
        else:
            start_idx = i
            break
            
    # Filter generic promotional / legal boilerplate at the end of the text
    cleaned = []
    for text in temp_paras[start_idx:]:
        if any(skip in text.lower() for skip in [
            "listen to escape pod", 
            "story begins at", 
            "produced by", 
            "copyright", 
            "originally published",
            "first published in",
            "podcastle is part of",
            "pseudopod is part of",
            "escape artists is part of",
            "escape artists foundation",
            "all rights reserved",
            "sleepphones"
        ]):
            continue
        cleaned.append(text)
        
    return cleaned

def extract_author(soup, p_tags):
    """
    Extracts the author of the story, first checking the postmeta div
    and falling back to the first few paragraphs if needed.
    """
    # Method 1: Look in postmeta div
    postmeta = soup.find(class_=re.compile(r"postmeta|post-meta"))
    if postmeta:
        text = postmeta.get_text(strip=True)
        # Search for Author: [name]
        match = re.search(r"Author:\s*([^N\n\r]+)", text)
        if match:
            author_raw = match.group(1).strip()
            # Split off standard trailing elements in the author line
            author_clean = re.split(
                r"Narrator:|Host:|Audio\s+Producer:|originally|first|published", 
                author_raw, 
                flags=re.IGNORECASE
            )[0].strip()
            if author_clean:
                return author_clean
                
    # Method 2: Fallback to searching first few paragraphs in the story content
    for p in p_tags[:5]:
        p_text = p.get_text(strip=True)
        author_match = re.match(r'^(?:by|written\s+by)\s+([A-Z\s\.\-\'\’]+)', p_text, re.IGNORECASE)
        if author_match:
            return author_match.group(1).strip()
            
    return "Unknown Author"

def extract_episode_details(episode_url):
    """
    Fetches an individual episode page and extracts the title, author, 
    date, and story content. Supports both old and new post formats.
    """
    print(f"Fetching story: {episode_url}")
    try:
        response = session.get(episode_url)
        if response.status_code != 200:
            print(f"Error fetching {episode_url}: HTTP {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract Title - Matches entry-title/post_title/post-title/entry_title
        title_tag = soup.find(class_=re.compile(r"^(post|entry)[-_]title$"))
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"
        
        # Try to parse episode number from title (e.g. "EP919: The Last Specimen")
        ep_match = re.search(r'\b(?:EP|Episode)\s*(\d+)\b', title, re.IGNORECASE)
        episode_num = ep_match.group(1) if ep_match else None
        
        # Extract Publish Date
        date_tag = soup.find("time", class_=re.compile(r"^entry[-_]date$"))
        date_str = date_tag.get_text(strip=True) if date_tag else None
        if not date_str:
            # Fallback for standard WordPress meta date tags
            date_meta = soup.find("meta", property="article:published_time")
            date_str = date_meta["content"] if date_meta else "Unknown Date"
            
        # Extract Content - matches both entry-content (old theme) and entry_content (new theme)
        content_div = soup.find("div", class_=re.compile(r"^entry[-_]content$")) or soup.find("div", class_="post-content")
        story_paragraphs = []
        author = "Unknown Author"
        
        if content_div:
            # Clean up unwanted elements inside the content (e.g., share buttons, player)
            for div in content_div.find_all(class_=re.compile("sharedaddy|jp-relatedposts|podcast-player|powerpress_player")):
                div.decompose()
                
            # Extract paragraphs
            p_tags = content_div.find_all("p")
            
            # Extract Author
            author = extract_author(soup, p_tags)
            
            # Clean and extract actual story paragraphs
            story_paragraphs = clean_story_paragraphs(p_tags)
        
        story_text = "\n\n".join(story_paragraphs)
        
        return {
            "episode_number": episode_num,
            "title": title,
            "author": author,
            "publish_date": date_str,
            "url": episode_url,
            "text": story_text
        }
        
    except Exception as e:
        print(f"Exception while scraping {episode_url}: {e}")
        return None

def get_episode_links(page_url):
    """
    Fetches a category listing page and returns all episode urls found on it.
    """
    print(f"Scanning listing page: {page_url}")
    try:
        response = session.get(page_url)
        if response.status_code == 404:
            print("Listing page returned 404. Reached the end of pagination.")
            return [], True
        if response.status_code != 200:
            print(f"Error fetching listing page: HTTP {response.status_code}")
            return [], False
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        # WordPress themes typically wrap article headers in h2.entry-title or h1.entry-title
        links = []
        headers = soup.find_all("h2", class_=re.compile(r"^entry[-_]title$"))
        if not headers:
            # Fallback: search for articles
            headers = soup.find_all("article")
            
        for header in headers:
            a_tag = header.find("a") if header.name != "a" else header
            if a_tag and a_tag.get("href"):
                url = a_tag.get("href")
                # Filter to ensure it looks like a post URL (not category, tag, author, etc.)
                if "/category/" not in url and "/tag/" not in url and "/author/" not in url:
                    links.append(url)
                    
        # If no links were found at all, we might have hit an empty page
        if not links:
            return [], True
            
        return links, False
        
    except Exception as e:
        print(f"Exception fetching listing page: {e}")
        return [], False

def main():
    page_num = 1
    scraped_count = 0
    skipped_count = 0
    consecutive_failures = 0
    
    # Create the sentinel RUN file if it doesn't exist to allow running
    if not os.path.exists(RUN_FILE):
        with open(RUN_FILE, "w") as f:
            pass
        print(f"Created sentinel file: {RUN_FILE}")
    else:
        print(f"Sentinel file '{RUN_FILE}' detected. Running scraper.")

    print("Starting Escape Pod story scraper...")
    print(f"Output directory: {OUTPUT_DIR}/")
    print(f"Rate-limiting delay: {DELAY_BETWEEN_REQUESTS} seconds per request")
    print(f"To stop the program safely, delete the file '{RUN_FILE}'.")
    
    graceful_stop = False
    
    while True:
        # Check sentinel file at the start of the pagination loop
        if not os.path.exists(RUN_FILE):
            print(f"\nSentinel file '{RUN_FILE}' was deleted. Initiating graceful shutdown...")
            graceful_stop = True
            break

        # Construct category page URL (WordPress pagination)
        if page_num == 1:
            page_url = BASE_URL
        else:
            page_url = urljoin(BASE_URL, f"page/{page_num}/")
            
        # Add delay before fetching the listing page
        time.sleep(DELAY_BETWEEN_REQUESTS)
        
        links, reached_end = get_episode_links(page_url)
        
        if reached_end or not links:
            break
            
        print(f"Found {len(links)} episode links on page {page_num}.")
        
        for link in links:
            # Check sentinel file at the start of each episode iteration
            if not os.path.exists(RUN_FILE):
                print(f"\nSentinel file '{RUN_FILE}' was deleted. Initiating graceful shutdown...")
                graceful_stop = True
                break

            # Create a unique filename for the episode
            # We can use the slug from the URL as a unique key
            url_slug = link.rstrip("/").split("/")[-1]
            filename = f"ep_{url_slug}.json"
            filepath = os.path.join(OUTPUT_DIR, filename)
            
            # Local Cache Check: Skip if we've already downloaded this story
            # Overwrite if it was previously saved with "Unknown Title"
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("text") and len(data["text"]) > 100 and data.get("title") != "Unknown Title":
                        skipped_count += 1
                        continue
                except:
                    pass  # If JSON is corrupted, re-download it
            
            # Rate-limit delay
            time.sleep(DELAY_BETWEEN_REQUESTS)
            
            story_data = extract_episode_details(link)
            if story_data and len(story_data["text"]) > 50 and story_data["title"] != "Unknown Title":
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(story_data, f, indent=4, ensure_ascii=False)
                print(f"Saved: {story_data['title']} -> {filepath}")
                scraped_count += 1
                consecutive_failures = 0  # Reset counter on successful parse
            else:
                print(f"Skipped/Failed to save: {link}")
                consecutive_failures += 1
                
                # Check for 10 consecutive failures
                if consecutive_failures >= 10:
                    print("\n" + "="*60)
                    print("CRITICAL WARNING: The scraper has encountered 10 consecutive failures.")
                    print("This indicates that the HTML structure of the website has changed")
                    print("and the parser is no longer able to extract story texts.")
                    print("Terminating program to prevent unnecessary server requests.")
                    print("="*60 + "\n")
                    graceful_stop = True
                    break
        
        if graceful_stop:
            break
            
        page_num += 1
        
    # Clean up sentinel file if the scraper completed fully on its own
    if not graceful_stop and os.path.exists(RUN_FILE):
        try:
            os.remove(RUN_FILE)
            print(f"Removed sentinel file '{RUN_FILE}' (run complete).")
        except Exception as e:
            print(f"Failed to remove sentinel file: {e}")

    print("\nScraping process ended.")
    print(f"Total stories scraped/saved: {scraped_count}")
    print(f"Total stories skipped (already cached): {skipped_count}")

if __name__ == "__main__":
    main()
