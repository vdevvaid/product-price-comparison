from flask import Flask, render_template, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import tempfile
import os
import time
from urllib.parse import urlencode
import openpyxl
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import asyncio
import aiohttp
import random
from fake_useragent import UserAgent
from cachetools import TTLCache

app = Flask(__name__)

class ProductScraper:
    def __init__(self):
        print("Initializing Chrome WebDriver...")
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        # Keep JavaScript enabled for Google Shopping
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        
        self.cache = TTLCache(maxsize=100, ttl=3600)
        
        # Define priority websites and their rankings
        self.priority_sellers = {
            'flipkart': 1,
            'reliance digital': 2,
            'jiomart': 3,
            'vijay sales': 4,
            'amazon': 5,
            'amazon.in': 5,
            'amazon india': 5,
            'croma': 6,
            'sangeetha': 7,
            'sangeetha mobiles': 7,
            'tata cliq': 8,
            'snapdeal': 9,
            'paytm mall': 10
        }
        
        try:
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
            self.driver.set_page_load_timeout(15)
            print("Chrome WebDriver initialized successfully")
        except Exception as e:
            print(f"Error initializing Chrome WebDriver: {e}")
            raise

    def get_seller_priority(self, merchant):
        merchant_lower = merchant.lower()
        for seller, priority in self.priority_sellers.items():
            if seller in merchant_lower:
                return priority
        return 999  # Non-priority sellers get high number

    def scrape_google_shopping(self, query):
        try:
            # Fetch more results at once by accessing multiple pages
            all_products = []
            pages_to_fetch = 6  # Google shows ~40 results per page, so 6 pages ≈ 250 results
            
            for page in range(pages_to_fetch):
                url = f"https://www.google.com/search?q={query}&hl=en&gl=in&tbm=shop&start={page * 40}"
                print(f"Accessing page {page + 1}, URL: {url}")
                
                self.driver.get(url)
                time.sleep(2)  # Short delay between pages
                
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.sh-dgr__content"))
                    )
                    
                    product_elements = self.driver.find_elements(By.CSS_SELECTOR, "div.sh-dgr__content")
                    if not product_elements:
                        break  # No more results found
                        
                    print(f"Found {len(product_elements)} products on page {page + 1}")
                    
                    for element in product_elements:
                        try:
                            # Product name
                            name_elem = element.find_element(By.CSS_SELECTOR, "h3.tAxDx")
                            name = name_elem.text.strip()
                            
                            # Skip accessories
                            if any(x in name.lower() for x in ['case', 'cover', 'screen guard', 'protector']):
                                continue
                            
                            # Price
                            try:
                                price_elem = element.find_element(By.CSS_SELECTOR, "span.a8Pemb")
                                price_text = price_elem.text.strip()
                                price = float(price_text.replace('₹', '').replace(',', '').split('.')[0])
                            except:
                                continue
                                
                            # Skip very low prices
                            if price < 5000:
                                continue
                            
                            # Merchant
                            try:
                                merchant_elem = element.find_element(By.CSS_SELECTOR, "div.aULzUe")
                                merchant = merchant_elem.text.strip()
                            except:
                                merchant = "Various Sellers"
                            
                            # URL
                            try:
                                url_elem = element.find_element(By.CSS_SELECTOR, "a.shntl")
                                url = url_elem.get_attribute('href')
                            except:
                                continue
                            
                            print(f"Found: {name} at ₹{price} from {merchant}")
                            
                            # Add priority to each product
                            all_products.append({
                                'Product Name': name,
                                'Price': price,
                                'Source': merchant,
                                'URL': url,
                                'priority': self.get_seller_priority(merchant)
                            })
                            
                        except Exception as e:
                            print(f"Error parsing product: {str(e)}")
                            continue
                            
                except Exception as e:
                    print(f"Error on page {page + 1}: {str(e)}")
                    break
                    
            # Sort by priority first, then by price
            all_products.sort(key=lambda x: (x['priority'], x['Price']))
            
            # Remove priority field before returning
            products_to_return = [{k: v for k, v in p.items() if k != 'priority'} 
                                for p in all_products]

            return {
                'products': products_to_return,
                'total_results': len(products_to_return)
            }
            
        except Exception as e:
            print(f"Scraping error: {str(e)}")
            return {
                'products': [],
                'total_results': 0
            }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form.get('query')
    start_index = int(request.form.get('start_index', 0))
    items_per_page = int(request.form.get('items_per_page', 15))

    if not query:
        return jsonify({'error': 'Please enter a search query'}), 400

    print(f"Searching for: {query} (start: {start_index})")
    scraper = None
    
    try:
        scraper = ProductScraper()
        result = scraper.scrape_google_shopping(query)
        
        if not result['products']:
            return jsonify({'error': 'No results found. Try a different search term or try again later.'}), 404

        # Create Excel file
        df = pd.DataFrame(result['products'])
        temp_dir = tempfile.mkdtemp()
        excel_path = os.path.join(temp_dir, 'products.xlsx')
        
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Price Comparison')
            worksheet = writer.sheets['Price Comparison']
            
            worksheet.column_dimensions['A'].width = 50
            worksheet.column_dimensions['B'].width = 15
            worksheet.column_dimensions['C'].width = 30
            
            for cell in worksheet['1:1']:
                cell.font = openpyxl.styles.Font(bold=True)
        
        return jsonify({
            'products': result['products'],
            'total_results': result['total_results'],
            'excel_path': excel_path
        })
        
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({'error': 'An error occurred while searching. Please try again.'}), 500
    finally:
        if scraper:
            try:
                scraper.driver.quit()
            except:
                pass

@app.route('/download/<path:filename>')
def download(filename):
    try:
        return send_file(filename, as_attachment=True, download_name='products.xlsx')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 