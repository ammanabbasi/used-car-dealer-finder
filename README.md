# Used Car Dealer Finder

A Streamlit web application that helps users find independent used car dealers in their area by zip code.

## Features

- Search for independent used car dealers by zip code
- View detailed dealer information:
  - Business name
  - Full address
  - Phone number
  - Website link
- Clean, modern interface
- Mobile-responsive design

## Technologies Used

- Python
- Streamlit
- Google Maps API
- OpenAI API
- BeautifulSoup4
- Trafilatura

## Setup

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up environment variables:
   - Create a `.env` file in the root directory
   - Add your API keys:
     ```
     OPENAI_API_KEY=your_openai_api_key
     GOOGLE_MAPS_API_KEY=your_google_maps_api_key
     ```
4. Run the app:
   ```
   streamlit run app.py
   ```

## Usage

1. Enter a 5-digit US zip code
2. Click "Find Dealers"
3. View the list of independent dealers in your area
4. Click on any dealer to see their full details

## License

MIT License 