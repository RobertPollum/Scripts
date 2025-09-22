import urllib.request
import urllib.error
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import time


class RequestParser:
    """
    A class for making HTTP requests and parsing HTML content to extract anchor tags.
    """
    
    def __init__(self, user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"):
        """
        Initialize the RequestParser with optional user agent.
        
        Args:
            user_agent (str): User agent string for HTTP requests
        """
        self.user_agent = user_agent
        self.headers = {'User-Agent': self.user_agent}
        self.url_cache = {}  # Cache for storing URL responses
        self.cache_timestamps = {}  # Track when URLs were cached
    
    def fetch_url(self, url: str, timeout: int = 30, use_cache: bool = True) -> Optional[str]:
        """
        Fetch content from a URL using urllib.request with caching support.
        
        Args:
            url (str): The URL to fetch
            timeout (int): Request timeout in seconds
            use_cache (bool): Whether to use cached content if available
            
        Returns:
            Optional[str]: The HTML content as string, or None if request failed
        """
        # Check cache first if enabled
        if use_cache and url in self.url_cache:
            print(f"Using cached content for URL: {url}")
            return self.url_cache[url]
        
        try:
            request = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                # Decode the response content
                content = response.read()
                encoding = response.headers.get_content_charset() or 'utf-8'
                decoded_content = content.decode(encoding, errors='ignore')
                
                # Cache the content
                self.url_cache[url] = decoded_content
                self.cache_timestamps[url] = time.time()
                print(f"Cached content for URL: {url}")
                
                return decoded_content
        except urllib.error.HTTPError as e:
            print(f"HTTP Error {e.code}: {e.reason} for URL: {url}")
            return None
        except urllib.error.URLError as e:
            print(f"URL Error: {e.reason} for URL: {url}")
            return None
        except Exception as e:
            print(f"Unexpected error fetching URL {url}: {str(e)}")
            return None
    
    def parse_anchor_tags(self, html_content: str) -> List[Dict[str, str]]:
        """
        Parse HTML content and extract all anchor tags.
        
        Args:
            html_content (str): HTML content to parse
            
        Returns:
            List[Dict[str, str]]: List of dictionaries containing anchor tag data
                                 Each dict has 'href', 'text', and 'title' keys
        """
        if not html_content:
            return []
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            anchor_tags = soup.find_all('a')
            
            parsed_anchors = []
            for anchor in anchor_tags:
                anchor_data = {
                    'href': anchor.get('href', ''),
                    'text': anchor.get_text(strip=True),
                    'title': anchor.get('title', ''),
                    'target': anchor.get('target', ''),
                    'class': ' '.join(anchor.get('class', [])) if anchor.get('class') else ''
                }
                parsed_anchors.append(anchor_data)
            
            return parsed_anchors
        except Exception as e:
            print(f"Error parsing HTML content: {str(e)}")
            return []
    
    def get_anchors_from_url(self, url: str, timeout: int = 30, use_cache: bool = True) -> List[Dict[str, str]]:
        """
        Fetch a URL and extract all anchor tags in one operation.
        
        Args:
            url (str): The URL to fetch and parse
            timeout (int): Request timeout in seconds
            use_cache (bool): Whether to use cached content if available
            
        Returns:
            List[Dict[str, str]]: List of anchor tag data dictionaries
        """
        html_content = self.fetch_url(url, timeout, use_cache)
        return self.parse_anchor_tags(html_content)
    
    def filter_anchors(self, anchors: List[Dict[str, str]], 
                      href_contains: Optional[str] = None,
                      text_contains: Optional[str] = None,
                      has_href: bool = True) -> List[Dict[str, str]]:
        """
        Filter anchor tags based on various criteria.
        
        Args:
            anchors (List[Dict[str, str]]): List of anchor dictionaries to filter
            href_contains (Optional[str]): Filter anchors where href contains this string
            text_contains (Optional[str]): Filter anchors where text contains this string
            has_href (bool): If True, only return anchors with non-empty href attributes
            
        Returns:
            List[Dict[str, str]]: Filtered list of anchor dictionaries
        """
        filtered = anchors.copy()
        
        if has_href:
            filtered = [a for a in filtered if a.get('href', '').strip()]
        
        if href_contains:
            filtered = [a for a in filtered if href_contains.lower() in a.get('href', '').lower()]
        
        if text_contains:
            filtered = [a for a in filtered if text_contains.lower() in a.get('text', '').lower()]
        
        return filtered
    
    def get_absolute_urls(self, anchors: List[Dict[str, str]], base_url: str) -> List[Dict[str, str]]:
        """
        Convert relative URLs to absolute URLs based on a base URL.
        
        Args:
            anchors (List[Dict[str, str]]): List of anchor dictionaries
            base_url (str): Base URL to resolve relative URLs against
            
        Returns:
            List[Dict[str, str]]: Anchors with absolute URLs
        """
        from urllib.parse import urljoin, urlparse
        
        result = []
        for anchor in anchors:
            anchor_copy = anchor.copy()
            href = anchor.get('href', '')
            if href:
                # Convert relative URLs to absolute
                absolute_url = urljoin(base_url, href)
                anchor_copy['href'] = absolute_url
                anchor_copy['is_external'] = urlparse(absolute_url).netloc != urlparse(base_url).netloc
            result.append(anchor_copy)
        
        return result

    def clear_cache(self) -> None:
        """
        Clear all cached URL content.
        """
        self.url_cache.clear()
        self.cache_timestamps.clear()
        print("URL cache cleared")

    def get_cache_stats(self) -> Dict[str, any]:
        """
        Get statistics about the current cache.
        
        Returns:
            Dict[str, any]: Dictionary containing cache statistics
        """
        current_time = time.time()
        cache_ages = {}
        
        for url, timestamp in self.cache_timestamps.items():
            cache_ages[url] = current_time - timestamp
        
        stats = {
            'cached_urls_count': len(self.url_cache),
            'cached_urls': list(self.url_cache.keys()),
            'cache_ages_seconds': cache_ages,
            'total_cache_size_chars': sum(len(content) for content in self.url_cache.values())
        }
        
        return stats

    def remove_from_cache(self, url: str) -> bool:
        """
        Remove a specific URL from the cache.
        
        Args:
            url (str): The URL to remove from cache
            
        Returns:
            bool: True if URL was in cache and removed, False otherwise
        """
        if url in self.url_cache:
            del self.url_cache[url]
            if url in self.cache_timestamps:
                del self.cache_timestamps[url]
            print(f"Removed {url} from cache")
            return True
        return False

    def is_cached(self, url: str) -> bool:
        """
        Check if a URL is currently cached.
        
        Args:
            url (str): The URL to check
            
        Returns:
            bool: True if URL is cached, False otherwise
        """
        return url in self.url_cache


# Example usage and testing
# if __name__ == "__main__":
#     parser = RequestParser()
    
#     # Example: Parse a webpage
#     url = "https://example.com"
#     print(f"Fetching anchors from: {url}")
    
#     anchors = parser.get_anchors_from_url(url)
#     print(f"Found {len(anchors)} anchor tags")
    
#     for i, anchor in enumerate(anchors[:5]):  # Show first 5
#         print(f"{i+1}. Text: '{anchor['text']}' -> URL: '{anchor['href']}'")
