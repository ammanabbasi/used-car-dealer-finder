import streamlit as st
import openai
import os
from dotenv import load_dotenv
import requests
import re
import json
import googlemaps
import time
from datetime import datetime
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
import trafilatura
from urllib.parse import urljoin, urlparse

# Load environment variables
load_dotenv()

# Initialize API clients
api_key = os.getenv("OPENAI_API_KEY")
google_api_key = os.getenv("GOOGLE_MAPS_API_KEY")

# Check for Streamlit secrets
if not api_key:
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except:
        st.error("OpenAI API key not found. Please set the OPENAI_API_KEY in your environment or Streamlit secrets.")
        st.stop()

if not google_api_key:
    try:
        google_api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
    except:
        st.error("Google Maps API key not found. Please set the GOOGLE_MAPS_API_KEY in your environment or Streamlit secrets.")
        st.stop()

# Set OpenAI API key
openai.api_key = api_key

# Initialize Google Maps client
gmaps = googlemaps.Client(key=google_api_key)

def verify_zipcode(zipcode):
    """Verify if the input is a valid US zipcode."""
    return bool(re.match(r'^\d{5}$', zipcode))

def format_business_hours(hours_text):
    """Format business hours into a clean list with current day highlighted."""
    if not hours_text:
        return "Hours not available"
    
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    current_day = datetime.now().strftime('%A')
    formatted_hours = []
    
    try:
        hours_lines = hours_text.split('\n')
        for day in days:
            current_class = ' class="current-day"' if day == current_day else ''
            for line in hours_lines:
                if line.startswith(day):
                    hours = line.split(': ')[1].strip()
                    formatted_hours.append(f"<li{current_class}><span>{day}</span><span>{hours}</span></li>")
                    break
            else:
                formatted_hours.append(f"<li{current_class}><span>{day}</span><span>Closed</span></li>")
        
        return f"<ul class='hours-list'>{''.join(formatted_hours)}</ul>"
    except Exception as e:
        st.warning(f"Error formatting hours: {str(e)}")
        return hours_text

def format_rating(rating_text):
    """Format rating with stars and Google-style display."""
    if not rating_text or rating_text == 'N/A':
        return "No ratings yet"
    
    try:
        rating, reviews = rating_text.split(' (')
        rating = float(rating)
        reviews = reviews.rstrip(' reviews)')
        full_stars = '★' * int(rating)
        half_star = '★' if rating % 1 >= 0.5 else '☆'
        empty_stars = '☆' * (4 - int(rating))
        stars = full_stars + half_star + empty_stars
        
        return f"""
        <div class="rating-value">
            <span class="rating-stars">{stars}</span>
            <span class="rating-number">{rating}</span>
            <span class="rating-count">({reviews})</span>
        </div>
        """
    except Exception as e:
        st.warning(f"Error formatting rating: {str(e)}")
        return rating_text

def get_dealer_info(zipcode):
    """Get real dealer information using Google Places API."""
    try:
        # First, get the location (lat/lng) for the zipcode
        geocode_result = gmaps.geocode(zipcode)
        
        if not geocode_result:
            st.error(f"Could not find location for zip code {zipcode}")
            return None
            
        location = geocode_result[0]['geometry']['location']
        
        dealers = []
        # Specific search queries for independent used car dealers
        search_queries = [
            'independent used car dealer',
            'used car dealer',
            'pre-owned car dealer',
            'used auto sales',
            'used vehicle dealer'
        ]
        
        with st.spinner("Searching for independent used car dealers..."):
            # Try each search query
            for query in search_queries:
                # Initial search with increased radius to find more dealers
                places_result = gmaps.places_nearby(
                    location=location,
                    radius=15000,  # 15km radius
                    keyword=query,
                    type='car_dealer'
                )
                
                # Process results
                if places_result.get('results'):
                    process_results(places_result.get('results'), dealers, zipcode)
                    
                    # Get next pages while available
                    while 'next_page_token' in places_result:
                        time.sleep(2)  # Wait for token to be valid
                        places_result = gmaps.places_nearby(
                            location=location,
                            page_token=places_result['next_page_token']
                        )
                        if places_result.get('results'):
                            process_results(places_result.get('results'), dealers, zipcode)
        
        # Remove duplicates based on place_id
        unique_dealers = {dealer['place_id']: dealer for dealer in dealers}.values()
        
        return list(unique_dealers)
        
    except Exception as e:
        st.error(f"Error finding dealer information: {str(e)}")
        return None

def process_results(results, dealers, target_zipcode):
    """Process place results and add to dealers list if zipcode matches."""
    for place in results:
        try:
            # Get detailed information for each place
            details = gmaps.place(place['place_id'], fields=[
                'name', 'formatted_address', 'formatted_phone_number',
                'website', 'place_id'
            ])['result']
            
            # Extract zipcode from address
            address = details.get('formatted_address', '')
            address_zipcode = extract_zipcode(address)
            
            # Only add dealer if zipcode matches
            if address_zipcode == target_zipcode:
                dealer = {
                    'business_name': details.get('name'),
                    'full_address': details.get('formatted_address'),
                    'phone_number': details.get('formatted_phone_number'),
                    'website': details.get('website'),
                    'place_id': place['place_id']
                }
                dealers.append(dealer)
            
            # Respect API rate limits
            time.sleep(0.1)
            
        except Exception as e:
            st.warning(f"Error processing dealer: {str(e)}")
            continue

def extract_zipcode(address):
    """Extract zipcode from formatted address."""
    try:
        # Look for 5-digit zipcode in the address
        match = re.search(r'[,\s](\d{5})[,\s-]', address)
        if match:
            return match.group(1)
    except:
        pass
    return None

def extract_website_info(url):
    """Extract and analyze information from dealer website."""
    try:
        st.write("Downloading website content...")  # Debug log
        
        # Try to get the webpage content
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            st.warning(f"Could not download content from {url}")
            return None
            
        # Extract main content
        st.write("Extracting main content...")  # Debug log
        text_content = trafilatura.extract(downloaded, include_links=True, include_images=False, include_tables=False)
        
        # Try BeautifulSoup if trafilatura fails
        if not text_content:
            st.write("Trying alternative content extraction...")  # Debug log
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
                
            # Get text content
            text_content = ' '.join(soup.stripped_strings)
        
        if not text_content:
            st.warning("Could not extract meaningful content from the website")
            return None
            
        st.write("Analyzing content with OpenAI...")  # Debug log
        
        # Use OpenAI to analyze the content
        analysis_prompt = f"""
        Analyze this car dealer website content and extract the following information in a structured format.
        Be thorough and try to find as much information as possible for each category.
        If you're not completely sure about something, include it anyway with appropriate wording.

        Website Content:
        {text_content[:4000]}

        Please extract and format the information into these categories:
        1. Inventory Highlights - What types of vehicles do they specialize in? What brands or types of cars do they mention?
        2. Special Offers - Any promotions, deals, or special financing offers mentioned?
        3. Financing Options - What financing services or options do they provide?
        4. Additional Services - What other services do they offer? (maintenance, warranties, etc.)
        5. Company Background - Any information about their history, experience, or reputation?
        6. Unique Selling Points - What makes them different from other dealers?
        7. Customer Policies - Any information about warranties, returns, or customer service policies?
        8. Contact Details - Look for any additional contact information such as:
           - Alternative phone numbers
           - Email addresses
           - Social media links
           - Fax numbers
           - Department-specific contacts
        9. Management/Staff - Look for information about:
           - Owner/dealer principal name
           - Management team
           - Key staff members
           - Years of experience
           - Professional certifications or affiliations

        Format the response as JSON with these exact keys:
        {{
            "inventory_highlights": ["point 1", "point 2", ...],
            "special_offers": ["offer 1", "offer 2", ...],
            "financing_options": ["option 1", "option 2", ...],
            "services": ["service 1", "service 2", ...],
            "company_background": "brief history",
            "unique_points": ["point 1", "point 2", ...],
            "policies": ["policy 1", "policy 2", ...],
            "contact_details": {{
                "phone_numbers": ["number 1", "number 2", ...],
                "emails": ["email 1", "email 2", ...],
                "social_media": ["link 1", "link 2", ...],
                "other_contact": ["detail 1", "detail 2", ...]
            }},
            "management_info": {{
                "owner": "name if available",
                "team": ["person 1 and role", "person 2 and role", ...],
                "experience": "years or description",
                "certifications": ["cert 1", "cert 2", ...]
            }}
        }}

        If you can't find information for a category, include it with an empty list or appropriate null values.
        Try to be comprehensive and include any relevant information you find.
        """

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo-16k",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at analyzing car dealer websites and extracting relevant business information. Be thorough and comprehensive in your analysis. Always return valid JSON."
                },
                {"role": "user", "content": analysis_prompt}
            ],
            temperature=0.5,
            max_tokens=2000
        )
        
        # Parse the response as JSON
        analysis = json.loads(response.choices[0].message.content)
        st.write("Analysis completed successfully!")  # Debug log
        return analysis
        
    except Exception as e:
        st.error(f"Error analyzing website: {str(e)}")
        st.write("Full error:", e)
        import traceback
        st.write("Traceback:", traceback.format_exc())
        return None

def format_website_analysis(analysis):
    """Format the website analysis into HTML."""
    if not analysis:
        return """
        <div class="info-group">
            <p class="info-label">Website Analysis</p>
            <div class="info-value">
                <p>Could not analyze website content. The website might be unavailable or require authentication.</p>
            </div>
        </div>
        """
        
    html = """
    <div class="analysis-section">
        <h3 class="section-title">🔍 Detailed Dealer Analysis</h3>
    """
    
    # Contact Details Section
    if analysis.get('contact_details'):
        contact_info = analysis['contact_details']
        html += """
        <div class="info-group contact-details">
            <p class="info-label">📞 Additional Contact Information</p>
            <div class="info-value">
        """
        
        if contact_info.get('phone_numbers'):
            html += """
            <div class="contact-section">
                <p class="contact-subtitle">Phone Numbers:</p>
                <ul class="feature-list">
            """
            for phone in contact_info['phone_numbers']:
                html += f'<li><span class="contact-icon">📱</span>{phone}</li>'
            html += "</ul></div>"
            
        if contact_info.get('emails'):
            html += """
            <div class="contact-section">
                <p class="contact-subtitle">Email Addresses:</p>
                <ul class="feature-list">
            """
            for email in contact_info['emails']:
                html += f'<li><span class="contact-icon">✉️</span>{email}</li>'
            html += "</ul></div>"
            
        if contact_info.get('social_media'):
            html += """
            <div class="contact-section">
                <p class="contact-subtitle">Social Media:</p>
                <ul class="feature-list">
            """
            for social in contact_info['social_media']:
                html += f'<li><span class="contact-icon">🔗</span>{social}</li>'
            html += "</ul></div>"
            
        if contact_info.get('other_contact'):
            html += """
            <div class="contact-section">
                <p class="contact-subtitle">Additional Contact Details:</p>
                <ul class="feature-list">
            """
            for detail in contact_info['other_contact']:
                html += f'<li><span class="contact-icon">ℹ️</span>{detail}</li>'
            html += "</ul></div>"
            
        html += "</div></div>"
    
    # Management/Staff Information
    if analysis.get('management_info'):
        mgmt_info = analysis['management_info']
        html += """
        <div class="info-group management-info">
            <p class="info-label">👥 Management & Staff</p>
            <div class="info-value">
        """
        
        if mgmt_info.get('owner'):
            html += f"""
            <div class="management-section">
                <p class="management-title">Owner/Dealer Principal:</p>
                <p class="owner-name">{mgmt_info['owner']}</p>
            </div>
            """
            
        if mgmt_info.get('team'):
            html += """
            <div class="management-section">
                <p class="management-title">Management Team:</p>
                <ul class="feature-list">
            """
            for member in mgmt_info['team']:
                html += f'<li><span class="contact-icon">👤</span>{member}</li>'
            html += "</ul></div>"
            
        if mgmt_info.get('experience'):
            html += f"""
            <div class="management-section">
                <p class="management-title">Experience:</p>
                <p class="experience-info">{mgmt_info['experience']}</p>
            </div>
            """
            
        if mgmt_info.get('certifications'):
            html += """
            <div class="management-section">
                <p class="management-title">Certifications & Affiliations:</p>
                <ul class="feature-list">
            """
            for cert in mgmt_info['certifications']:
                html += f'<li><span class="contact-icon">🏅</span>{cert}</li>'
            html += "</ul></div>"
            
        html += "</div></div>"
    
    # Inventory Highlights
    if analysis.get('inventory_highlights'):
        html += """
        <div class="info-group">
            <p class="info-label">🚗 Inventory Specialties</p>
            <div class="info-value">
                <ul class="feature-list highlight-list">
        """
        for item in analysis['inventory_highlights']:
            html += f"<li>{item}</li>"
        html += "</ul></div></div>"
    
    # Special Offers
    if analysis.get('special_offers'):
        html += """
        <div class="info-group">
            <p class="info-label">🏷️ Current Offers & Promotions</p>
            <div class="info-value">
                <ul class="feature-list highlight-list">
        """
        for offer in analysis['special_offers']:
            html += f"<li>{offer}</li>"
        html += "</ul></div></div>"
    
    # Financing Options
    if analysis.get('financing_options'):
        html += """
        <div class="info-group">
            <p class="info-label">💳 Financing Solutions</p>
            <div class="info-value">
                <ul class="feature-list">
        """
        for option in analysis['financing_options']:
            html += f"<li>{option}</li>"
        html += "</ul></div></div>"
    
    # Services
    if analysis.get('services'):
        html += """
        <div class="info-group">
            <p class="info-label">🔧 Services & Support</p>
            <div class="info-value">
                <ul class="feature-list">
        """
        for service in analysis['services']:
            html += f"<li>{service}</li>"
        html += "</ul></div></div>"
    
    # Company Background
    if analysis.get('company_background'):
        html += f"""
        <div class="info-group">
            <p class="info-label">📖 About the Dealer</p>
            <div class="info-value">
                <div class="company-background">
                    <p>{analysis['company_background']}</p>
                </div>
            </div>
        </div>
        """
    
    # Unique Points
    if analysis.get('unique_points'):
        html += """
        <div class="info-group">
            <p class="info-label">✨ Why Choose This Dealer</p>
            <div class="info-value">
                <ul class="feature-list highlight-list">
        """
        for point in analysis['unique_points']:
            html += f"<li>{point}</li>"
        html += "</ul></div></div>"
    
    # Policies
    if analysis.get('policies'):
        html += """
        <div class="info-group">
            <p class="info-label">📋 Customer Policies & Guarantees</p>
            <div class="info-value">
                <ul class="feature-list">
        """
        for policy in analysis['policies']:
            html += f"<li>{policy}</li>"
        html += "</ul></div></div>"
    
    # Add a note about the analysis
    html += """
    <div class="info-group">
        <p class="info-note">This analysis is based on the dealer's website content and may not be complete or up-to-date. Please contact the dealer directly for the most current information.</p>
    </div>
    """
    
    html += "</div>"
    return html

def create_dealer_html(dealer):
    """Create simplified HTML for dealer card with only essential information."""
    website_link = dealer.get('website')
    website_html = f'<a href="{website_link}" target="_blank">{website_link}</a>' if website_link else 'N/A'

    dealer_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            body {{
                margin: 0;
                padding: 16px;
            }}
            .dealer-card {{
                background-color: #ffffff;
                padding: 24px;
                border-radius: 8px;
                box-shadow: 0 1px 2px rgba(60,64,67,.3);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                width: 100%;
            }}
            .dealer-name {{
                color: #202124;
                font-size: 24px;
                margin-bottom: 24px;
                padding-bottom: 12px;
                border-bottom: 2px solid #1a73e8;
            }}
            .info-group {{
                padding: 16px;
                margin-bottom: 16px;
                background-color: #f8f9fa;
                border-radius: 4px;
                border: 1px solid #e0e0e0;
            }}
            .info-group:last-child {{
                margin-bottom: 0;
            }}
            .info-label {{
                color: #5f6368;
                font-size: 14px;
                font-weight: 500;
                margin-bottom: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .info-value {{
                color: #202124;
                font-size: 16px;
                line-height: 1.6;
                word-break: break-word;
            }}
            .info-value a {{
                color: #1a73e8;
                text-decoration: none;
            }}
            .info-value a:hover {{
                text-decoration: underline;
            }}
            .contact-info {{
                display: flex;
                align-items: flex-start;
                gap: 12px;
            }}
            .contact-icon {{
                color: #5f6368;
                font-size: 20px;
                flex-shrink: 0;
                width: 24px;
                text-align: center;
                margin-top: 2px;
            }}
            .contact-text {{
                flex-grow: 1;
                min-width: 0;
            }}
            @media (max-width: 600px) {{
                body {{
                    padding: 8px;
                }}
                .dealer-card {{
                    padding: 16px;
                }}
                .info-group {{
                    padding: 12px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="dealer-card">
            <h2 class="dealer-name">{dealer.get('business_name', 'Unknown Dealer')}</h2>
            
            <div class="info-group">
                <p class="info-label">Address</p>
                <div class="contact-info">
                    <span class="contact-icon">📍</span>
                    <div class="contact-text">
                        <p class="info-value">{dealer.get('full_address', 'N/A')}</p>
                    </div>
                </div>
            </div>
            
            <div class="info-group">
                <p class="info-label">Phone</p>
                <div class="contact-info">
                    <span class="contact-icon">📞</span>
                    <div class="contact-text">
                        <p class="info-value">{dealer.get('phone_number', 'N/A')}</p>
                    </div>
                </div>
            </div>
            
            <div class="info-group">
                <p class="info-label">Website</p>
                <div class="contact-info">
                    <span class="contact-icon">🌐</span>
                    <div class="contact-text">
                        <p class="info-value">{website_html}</p>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return dealer_html

# Custom CSS for modern interface
st.markdown("""
    <style>
    .stApp {
        max-width: 1200px;
        margin: 0 auto;
        font-family: 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .search-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        margin-top: 50px;
        margin-bottom: 30px;
    }
    .title {
        color: #1a73e8;
        font-size: 48px;
        margin-bottom: 20px;
        text-align: center;
        font-weight: 400;
    }
    .subtitle {
        color: #5f6368;
        font-size: 18px;
        margin-bottom: 30px;
        text-align: center;
    }
    .dealer-card {
        background-color: #ffffff;
        padding: 24px;
        border-radius: 8px;
        box-shadow: 0 1px 2px rgba(60,64,67,.3), 0 1px 3px 1px rgba(60,64,67,.15);
        margin-bottom: 24px;
        transition: box-shadow 0.2s ease;
    }
    .dealer-card:hover {
        box-shadow: 0 1px 3px rgba(60,64,67,.3), 0 4px 8px 3px rgba(60,64,67,.15);
    }
    .dealer-name {
        color: #202124;
        font-size: 28px;
        margin-bottom: 16px;
        font-weight: 400;
        padding-bottom: 12px;
        border-bottom: 1px solid #dadce0;
    }
    .info-group {
        padding: 20px;
        margin-bottom: 16px;
        border-radius: 8px;
        background-color: #f8f9fa;
        transition: all 0.2s ease;
        border: 1px solid #dadce0;
    }
    .info-group:hover {
        background-color: #f1f3f4;
        border-color: #1a73e8;
        transform: translateY(-1px);
        box-shadow: 0 1px 2px rgba(60,64,67,.3), 0 1px 3px 1px rgba(60,64,67,.15);
    }
    .info-label {
        color: #5f6368;
        font-size: 14px;
        font-weight: 500;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .info-value {
        color: #202124;
        font-size: 16px;
        line-height: 1.5;
    }
    .info-value a {
        color: #1a73e8;
        text-decoration: none;
        font-weight: 500;
    }
    .info-value a:hover {
        text-decoration: underline;
    }
    .hours-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    .hours-list li {
        display: flex;
        justify-content: space-between;
        padding: 8px 0;
        color: #202124;
    }
    .hours-list li span:first-child {
        color: #5f6368;
        font-weight: 500;
        margin-right: 24px;
        min-width: 100px;
    }
    .hours-list li.current-day {
        color: #1a73e8;
        font-weight: 500;
    }
    .rating-value {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .rating-stars {
        color: #fdd663;
        font-size: 20px;
        letter-spacing: 1px;
    }
    .rating-number {
        color: #202124;
        font-weight: 500;
        font-size: 16px;
    }
    .rating-count {
        color: #5f6368;
        font-size: 14px;
    }
    .contact-info {
        display: flex;
        align-items: flex-start;
        gap: 8px;
    }
    .contact-icon {
        color: #5f6368;
        font-size: 20px;
        min-width: 24px;
        text-align: center;
        margin-top: 2px;
    }
    .phone-number {
        color: #1a73e8;
        font-weight: 500;
    }
    .section-title {
        color: #202124;
        font-size: 24px;
        font-weight: 500;
        margin: 24px 0 20px;
        padding-bottom: 12px;
        border-bottom: 2px solid #1a73e8;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .feature-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    .feature-list li {
        padding: 12px 0;
        border-bottom: 1px solid #eee;
        line-height: 1.6;
    }
    .feature-list li:last-child {
        border-bottom: none;
    }
    .highlight-list li {
        color: #1a73e8;
        font-weight: 500;
        position: relative;
        padding-left: 24px;
    }
    .highlight-list li:before {
        content: '•';
        position: absolute;
        left: 8px;
        color: #1a73e8;
    }
    .company-background {
        padding: 16px;
        background-color: #e8f0fe;
        border-radius: 8px;
        border-left: 4px solid #1a73e8;
        line-height: 1.6;
        margin: 8px 0;
    }
    .company-background p {
        margin: 0;
        color: #202124;
    }
    .analysis-section {
        margin-top: 32px;
        border-top: 3px solid #1a73e8;
        padding-top: 24px;
    }
    .contact-details, .management-info {
        background-color: #f8f9fa;
        border: 1px solid #dadce0;
        margin-bottom: 24px;
    }
    .contact-section, .management-section {
        margin-bottom: 20px;
    }
    .contact-section:last-child, .management-section:last-child {
        margin-bottom: 0;
    }
    .contact-subtitle, .management-title {
        color: #1a73e8;
        font-weight: 500;
        font-size: 16px;
        margin-bottom: 8px;
    }
    .owner-name {
        font-size: 18px;
        color: #202124;
        font-weight: 500;
        margin: 8px 0;
    }
    .experience-info {
        color: #202124;
        font-style: italic;
        margin: 8px 0;
    }
    .info-note {
        color: #5f6368;
        font-size: 14px;
        font-style: italic;
        margin-top: 16px;
        padding: 12px;
        background-color: #f8f9fa;
        border-radius: 4px;
        border-left: 4px solid #1a73e8;
    }
    </style>
""", unsafe_allow_html=True)

# App header
st.markdown('<h1 class="title">Independent Used Car Dealer Finder</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Find independent used car dealers in your area</p>', unsafe_allow_html=True)

# Zipcode input
zipcode = st.text_input("Enter Zip Code", placeholder="e.g., 20136", max_chars=5)

if st.button("Find Dealers", type="primary"):
    if not zipcode:
        st.warning("Please enter a zip code.")
    elif not verify_zipcode(zipcode):
        st.error("Please enter a valid 5-digit zip code.")
    else:
        with st.spinner(f"Finding independent used car dealers in {zipcode}..."):
            dealers = get_dealer_info(zipcode)
            
            if dealers and len(dealers) > 0:
                st.success(f"Found {len(dealers)} independent dealers in {zipcode}")
                
                for dealer in dealers:
                    try:
                        dealer_name = dealer.get('business_name', 'Unknown Dealer')
                        with st.expander(f"🚗 {dealer_name}", expanded=False):
                            dealer_html = create_dealer_html(dealer)
                            components.html(dealer_html, height=500, scrolling=False)
                    except Exception as e:
                        st.error(f"Error displaying dealer information: {str(e)}")
            else:
                st.error(f"No independent dealers found in zipcode {zipcode}. Try a different zip code.")