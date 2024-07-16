import concurrent.futures
import datetime
import json
import os
import time
from urllib.parse import urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
import openai  # For accessing the openai module's functionalities
from openai import OpenAI  # For direct use of the OpenAI class
from llama_index.llms.openai import OpenAI as llamaOpenAI
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, ServiceContext
from llama_index.core import Document
# from st_copy_to_clipboard import st_copy_to_clipboard
from prompts import *
import markdown2
 
from sqlalchemy import create_engine, Column, Integer, String, Text, MetaData, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import or_

# Function to save a transcript
def save_transcript(transcript_content, role, specialty):
    new_transcript = Transcript(content=transcript_content, role=role, specialty=specialty)
    session.add(new_transcript)
    session.commit()

# Function to save an assessment
def save_assessment(assessment_content, role, specialty):
    new_assessment = Assessment(content=assessment_content, role=role, specialty=specialty)
    session.add(new_assessment)
    session.commit()

# Function to save case details
def save_case_details(case_details_content, role, specialty):
    new_case_details = CaseDetails(content=case_details_content, role=role, specialty=specialty)
    session.add(new_case_details)
    session.commit()

# Function to retrieve records with full-text search and wildcards
def get_records(model, search_text=None, role=None, specialty=None):
    query = session.query(model)
    if search_text:
        search_text = f"%{search_text}%"  # Wildcard search
        query = query.filter(model.content.ilike(search_text))
    if role:
        query = query.filter_by(role=role)
    if specialty:
        query = query.filter_by(specialty=specialty)
    return query.all()

# Database setup
DATABASE_URL = "sqlite:///app_data.db"  # SQLite database

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()

# Define the models
class Transcript(Base):
    __tablename__ = 'transcripts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)
    specialty = Column(String, nullable=True)
    __table_args__ = (Index('transcript_content_idx', 'content', postgresql_using='gin'),)

class Assessment(Base):
    __tablename__ = 'assessments'
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)
    specialty = Column(String, nullable=True)
    __table_args__ = (Index('assessment_content_idx', 'content', postgresql_using='gin'),)

class CaseDetails(Base):
    __tablename__ = 'case_details'
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    role = Column(String, nullable=False)
    specialty = Column(String, nullable=True)
    __table_args__ = (Index('case_details_content_idx', 'content', postgresql_using='gin'),)

# Create tables
Base.metadata.create_all(engine)

st.set_page_config(page_title='My AI Team', layout = 'centered', page_icon = ':stethoscope:', initial_sidebar_state = 'auto')


@st.cache_data
def json_data_to_string(json_data):
    """
    Converts JSON data (Python dictionary or list) into a string representation.

    Parameters:
    - json_data: The JSON data as a Python object (typically a dictionary or list).

    Returns:
    - A string representation of the JSON data.
    """
    try:
        # Converting the JSON data to a string representation
        data_as_string = json.dumps(json_data, indent=2)
        return data_as_string
    except Exception as e:
        st.warning(f"An error occurred while converting JSON data to string: {e}")
        return None

# def get_summary_from_qa(chain_type, summary_template):
#     with st.spinner("Generating summary for a custom chatbot"):
#         qa = RetrievalQA.from_chain_type(llm=llm, chain_type=chain_type, retriever=retriever, return_source_documents=True)
#         index_context = f'Use only the reference document for knowledge. Question: {summary_template}'
#         summary_for_chatbot = qa(index_context)
#         return summary_for_chatbot["result"]

@st.cache_data
def truncate_after_n_words(text, n=10000):
    """
    Truncate the text after n words.

    Parameters:
    - text (str): The input text to truncate.
    - n (int): The number of words to keep in the truncated text. Defaults to 10,000.

    Returns:
    - str: The truncated text.
    """
    words = text.split()  # Split the text into words
    truncated_words = words[:n]  # Keep only the first n words
    truncated_text = ' '.join(truncated_words)  # Reassemble the text from the first n words
    return truncated_text

# Function to load configuration either from Streamlit secrets or environment variables
def load_config(keys):
    # Check if running on Streamlit Cloud
    if 'STREAMLIT_SHARING_MODE' in os.environ:
        # Use Streamlit secrets
        for key in keys:
            config[key] = st.secrets.get(key)
    else:
        # Use environment variables
        for key in keys:
            config[key] = os.environ.get(key)

@st.cache_data
def realtime_search(query, domains, max):
    url = "https://real-time-web-search.p.rapidapi.com/search"
    
    # Combine domains and query
    full_query = f"{domains} {query}"
    querystring = {"q": full_query, "limit": max}

    headers = {
        "X-RapidAPI-Key": st.secrets["X-RapidAPI-Key"],
        "X-RapidAPI-Host": "real-time-web-search.p.rapidapi.com",
    }

    urls = []
    snippets = []

    try:
        response = requests.get(url, headers=headers, params=querystring)
        
        # Check if the request was successful
        if response.status_code == 200:
            response_data = response.json()
            # st.write(response_data.get('data', []))
            for item in response_data.get('data', []):
                urls.append(item.get('url'))   
                snippets.append(f"**{item.get('title')}**  \n*{item.get('snippet')}*  \n{item.get('url')} <END OF SITE>")

        else:
            st.error(f"Search failed with status code: {response.status_code}")
            return [], []

    except requests.exceptions.RequestException as e:
        st.error(f"RapidAPI real-time search failed to respond: {e}")
        return [], []

    return snippets, urls


@st.cache_data
def extract_domains(domains):
    """
    Function to extract domain names from a string.
    
    Parameters:
    domains (str): The string containing the domain names.

    Returns:
    list: A list of domain names.
    """
    # Split the string into individual sites
    sites = domains.split(' OR ')

    # Extract the domain name from each site
    domain_names = [site.replace('site:', '') for site in sites]

    return domain_names

@st.cache_data
def websearch_snippets(web_query: str, domains, max):

    
    web_query = domains + " " + web_query
    # st.info(f'Here is the websearch input: **{web_query}**')
    url = "https://real-time-web-search.p.rapidapi.com/search"
    querystring = {"q":web_query,"limit":max}
    headers = {
        "X_RapidAPI_Key": config["X_RapidAPI_Key"],
        "X-RapidAPI-Host": "real-time-web-search.p.rapidapi.com"
    }

    response = requests.get(url, headers=headers, params=querystring)
    response_data = response.json()
    # response_data = join_and_clean_snippets(response_data.text)
    # def display_search_results(json_data):
    #     data = json_data['data']
    #     for item in data:
    #         st.sidebar.markdown(f"### [{item['title']}]({item['url']})")
    #         st.sidebar.write(item['snippet'])
    #         st.sidebar.write("---")
    # st.info('Searching the web using: **{web_query}**')
    # display_search_results(response_data)
    # st.session_state.done = True
    urls = []
    snippets = []
    for item in response_data['data']:
        urls.append(item['url'])   
        snippets.append(item['snippet'])
    st.write(urls)
    st.write(snippets)
    return snippets, urls

@st.cache_data
def websearch_snippets_old(web_query, domains, max):
    web_query = domains + " " + web_query
    api_url = "https://real-time-web-search.p.rapidapi.com/search"
    querystring = {"q":web_query,"limit":max}
    headers = {
        "X_RapidAPI_Key": config["X_RapidAPI_Key"],
        "X-RapidAPI-Host": "real-time-web-search.p.rapidapi.com"
    }

    response = requests.get(api_url, headers=headers, params=querystring)
    response_data = response.json()
    all_snippets = []
    urls = []
    for item in response_data['data']:
        all_snippets.append(f"{item['title']} {item['snippet']}  {item['url']}  <END OF SITE>" )
        urls.append(item['url'])
    

    # st.info("Web snippets reviewed.")
    st.write(f'HERE IS THE SNIPPETS RESPONSE: {all_snippets}')
    st.write(f'HERE ARE THE URLS: {urls}')
    
    return all_snippets, urls

@st.cache_data
def join_and_clean_snippets(snippets, separator=' <END OF SITE> '):
    """
    Function to join snippets of HTML content from multiple sites into a single string, and then clean and split the joined HTML.
    
    Parameters:
    snippets (list): A list of HTML snippets.
    separator (str): The separator used to join the snippets.

    Returns:
    list: A list of paragraphs.
    """
    st.write(f'Here is the snippets input: {snippets}')
    # Join the snippets into a single string with the separator
    full_html = separator.join(snippets)

    # Clean and split the joined HTML
    paragraphs = clean_and_split_html(full_html, separator)

    return paragraphs

@st.cache_data
def clean_and_split_html(full_html, separator=' <END OF SITE> '):
    """
    Function to remove HTML tags from a string and split the cleaned text into paragraphs.
    
    Parameters:
    full_html (str): The HTML string to be cleaned and split.
    separator (str): The separator used to split the full_html into individual site contents.

    Returns:
    list: A list of paragraphs.
    """
    # Split the full_html into individual site contents
    site_contents = full_html.split(separator)

    # List of tags to consider when splitting the text
    tags = ['p', 'div', 'section', 'article', 'aside', 'details', 'figcaption', 'figure', 
            'footer', 'header', 'main', 'mark', 'nav', 'summary', 'time']

    all_paragraphs = []

    # Process each site's content individually
    for html in site_contents:
        # Parse the HTML with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        # Find all the tags in the HTML
        found_tags = soup.find_all(tags)

        # Extract the text from each tag and store in a list
        paragraphs = [tag.get_text(strip=True) for tag in found_tags]

        # If no tags were found, fall back to splitting the text by newline characters
        if not paragraphs:
            text = ' '.join(soup.stripped_strings).replace('\n', ' ').replace('\r', '')
            paragraphs = text.split('\n')

        all_paragraphs.extend(paragraphs)

    return all_paragraphs


    
@st.cache_data
def browserless(url_list, max):
    # st.write(f'Pages scraped:\n\n{url_list}')
    # st.write(url_list)
    # if max > 5:
    #     max = 5
    response_complete = []
    i = 0
    key = config["BROWSERLESS_API_KEY"]
    # api_url = f'https://chrome.browserless.io/content?token={key}&proxy=residential&proxyCountry=us&proxySticky'
    api_url = f'https://chrome.browserless.io/content?token={key}'

    headers = {
        # 'Cache-Control': 'no-cache',
        'Content-Type': 'application/json'
    }
    while i < max and i < len(url_list):
        url = url_list[i]
        url_parts = urlparse(url)
        # st.write("Scraping...")
        if 'uptodate.com' in url_parts.netloc:
            method = "POST"
            url_parts = url_parts._replace(path=url_parts.path + '/print')
            url = urlunparse(url_parts)
            # st.write(f' here is a {url}')
        payload =  {
            "url": url,
            "waitFor": 3000,
            # "rejectResourceTypes": ["image"],
        }
        
        response = requests.post(api_url, headers=headers, json=payload)
        # response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            st.write(f'One of the sites failed to release all content: {response.status_code}')
            # st.write(f'Response text: {response.text}')
            # st.write(f'Response headers: {response.headers}')
        try:
            # st.write(f'Response text: {response.text}')  # Print out the raw response text
            # soup = BeautifulSoup(response.text, 'html.parser')
            # clean_text = soup.get_text(separator=' ')
            # # st.write(clean_text)
            # # st.write("Scraped!")
            response_complete.append(response.text)
        except json.JSONDecodeError:
            st.write("Error decoding JSON")
        i += 1
    full_response_str = ' <END OF SITE> '.join(response_complete)
    full_response = clean_and_split_html(full_response_str)
    # limited_text = limit_tokens(full_response, 12000)
    # st.write(f'Here is the lmited text: {limited_text}')
    return full_response

# @st.cache_data
# def limit_tokens(text, max_tokens=10000):
#     tokens = text.split()  # split the text into tokens (words)
#     limited_tokens = tokens[:max_tokens]  # keep the first max_tokens tokens
#     limited_text = ' '.join(limited_tokens)  # join the tokens back into a string
#     return limited_text

@st.cache_data
def scrapeninja(url_list, max):
    st.write(f'here are urls going to scrapeninja {url_list}')
    # st.write(url_list)
    if max > 5:
        max = 5
    response_complete = []
    i = 0
    method = "POST"
    key = config["X_RapidAPI_Key"]
    headers = {
        "content-type": "application/json",
        "X_RapidAPI_Key": key,
        "X-RapidAPI-Host": "scrapeninja.p.rapidapi.com",
    }
    while i < max and i < len(url_list):
        url = url_list[i]
        url_parts = urlparse(url)
        # st.write("Scraping...")
        if 'uptodate.com' in url_parts.netloc:
            method = "POST"
            url_parts = url_parts._replace(path=url_parts.path + '/print')
            url = urlunparse(url_parts)
            st.write(f' here is a {url}')
        payload =  {
            "url": url,
            "method": "POST",
            "retryNum": 1,
            "geo": "us",
            "js": True,
            "blockImages": False,
            "blockMedia": False,
            "steps": [],
            "extractor": "// define function which accepts body and cheerio as args\nfunction extract(input, cheerio) {\n    // return object with extracted values              \n    let $ = cheerio.load(input);\n  \n    let items = [];\n    $('.titleline').map(function() {\n          \tlet infoTr = $(this).closest('tr').next();\n      \t\tlet commentsLink = infoTr.find('a:contains(comments)');\n            items.push([\n                $(this).text(),\n              \t$('a', this).attr('href'),\n              \tinfoTr.find('.hnuser').text(),\n              \tparseInt(infoTr.find('.score').text()),\n              \tinfoTr.find('.age').attr('title'),\n              \tparseInt(commentsLink.text()),\n              \t'https://news.ycombinator.com/' + commentsLink.attr('href'),\n              \tnew Date()\n            ]);\n        });\n  \n  return { items };\n}"
        }
        
        response = requests.request(method, url, json=payload, headers=headers)
        # response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            st.write(f'The site failed to release all content: {response.status_code}')
            # st.write(f'Response text: {response.text}')
            # st.write(f'Response headers: {response.headers}')
        try:
            # st.write(f'Response text: {response.text}')  # Print out the raw response text
            soup = BeautifulSoup(response.text, 'html.parser')
            clean_text = soup.get_text(separator=' ')
            # st.write(clean_text)
            # st.write("Scraped!")
            response_complete.append(clean_text)
        except json.JSONDecodeError:
            st.write("Error decoding JSON")
        i += 1
    full_response = ' '.join(response_complete)
    # limited_text = limit_tokens(full_response, 12000)
    # st.write(f'Here is the lmited text: {limited_text}')
    return full_response
    # st.write(full_response)    
    # Join all the scraped text into a single string
    # return full_response

@st.cache_data
def reconcile(question, model, old, new, web_content, reconcile_prompt):
    # Send a message to the model asking it to summarize the text
    openai.api_base = "https://api.openai.com/v1/"
    openai.api_key = config['OPENAI_API_KEY']
    # truncated_web_content = truncate_after_n_words(web_content, 10000)
    try:
        response = client.chat.completions.create(
            model= model,
            messages=[
                {"role": "system", "content": reconcile_prompt},
                {"role": "user", "content": f' User question: {question} \n\n, prior answer 1" {old} \n\n, prior answer 2: {new} \n\n, web evidence: {web_content} \n\n'}
            ]
        )
    except:
        st.error("Error in reconciling the evidence.")
    # Return the content of the model's response
    return response.choices[0].message.content



@st.cache_data
def answer_using_prefix(prefix, sample_question, sample_answer, my_ask, temperature, history_context, model, print = False):
    if model == "openai/gpt-3.5-turbo-1106":
        model = "gpt-3.5-turbo-1106"
    if model == "openai/gpt-3.5-turbo":
        model = "gpt-3.5-turbo"
    if model == "openai/gpt-3.5-turbo-16k":
        model = "gpt-3.5-turbo-16k"
    if model == "openai/gpt-4":
        model = "gpt-4"
    if model == "openai/gpt-4-1106-preview":
        model = "gpt-4-1106-preview"
    if model == "openai/gpt-4-turbo-preview":
        model = "gpt-4-turbo-preview"
    if history_context == None:
        history_context = ""
    messages = [{'role': 'system', 'content': prefix},
            {'role': 'user', 'content': sample_question},
            {'role': 'assistant', 'content': sample_answer},
            {'role': 'user', 'content': history_context + my_ask},]
    if model == "gpt-4" or model == "gpt-3.5-turbo" or model == "gpt-3.5-turbo-16k" or model == "gpt-4-1106-preview" or model == "gpt-3.5-turbo-1106" or model == "gpt-4-turbo-preview":
        openai.api_base = "https://api.openai.com/v1/"
        openai.api_key = config['OPENAI_API_KEY']
        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model = model,
            messages = messages,
            temperature = temperature,
            max_tokens = 1500,
            stream = False,   
        )
        response= response.choices[0].message.content
        # response = response['choices'][0]['message']["content"]
    else:      
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",

            # model = model,
            # messages = messages,
            headers={"Authorization": "Bearer " + config["OPENROUTER_API_KEY"], # To identify your app
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://fsm-gpt-med-ed.streamlit.app", # To identify your app
                    "X-Title": "GPT and Med Ed",
                },
            data=json.dumps({
                "model": model, # Optional
                "messages": messages, # Optional
            })
            )
        response = response.json()
        response = response['choices'][0]['message']["content"]
    return response # Change how you access the message content

def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == config["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.write("*Please contact David Liebovitz, MD if you need an updated password for access.*")
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True



st.title("My AI Team")
with st.expander("Please read before using"):
    st.write("This app is a demonstration of consensus approaches to answering clinical questions using AI. It is not intended for direct clinical use. Always validate answers independently before using them in clinical practice. This app is for educational purposes only.")
    st.info("You may use default settings or modify them by selecting the models on the left sidebar that you would like to use to answer your question. The first two models will be used to generate answers, and the third model will be used to reconcile the two answers and any web search results.")
    st.warning("Please note this is a demo of late-breaking methods and there may be errors. Validate all answers independently before *thinking* of leveraging answers beyond just AI exploration.")
    st.write("Author: David Liebovitz, MD")
st.warning("""Large language models (LLMs) hallucinate. This is particularly a concern in any healthcare context. Here, early methods
           to mitigate this are used including [CoVE](https://arxiv.org/abs/2309.11495) and grounding the final output with web content from reliable sites.
           The links provided to the user (independent of the LLMs) are also intended to assist with answering your question and may 
           be used for the user to help validate the LLM content""")

if 'user_question' not in st.session_state:
    st.session_state['user_question'] = ''
    
if 'improved_question' not in st.session_state:
    st.session_state['improved_question'] = ''
    
if 'final_question' not in st.session_state:
    st.session_state['final_question'] = ''
    
if 'model1_response' not in st.session_state:
    st.session_state['model1_response'] = ''
    
if 'model2_response' not in st.session_state:
    st.session_state['model2_response'] = ''
    
if 'final_response' not in st.session_state:
    st.session_state['final_response'] = ''
    
if 'web_response' not in st.session_state:
    st.session_state['web_response'] = []
    
if 'ebm' not in st.session_state:
    st.session_state.ebm = ''
    
if 'thread' not in st.session_state:
    st.session_state.thread =[]
    
if 'domain_list' not in st.session_state:
    st.session_state.domain_list = domain_list
    
if 'snippets' not in st.session_state:
    st.session_state.snippets = []
    
# List of configuration keys expected in the secrets or environment variables
keys = [
    "password",
    "OPENAI_API_KEY",
    "X_RapidAPI_Key",
    "X_USER_ID",
    "OPENROUTER_API_KEY",
    "pubmed_api_key",
    "BROWSERLESS_API_KEY",
    "S2_API_KEY"
]

# Initialize a dictionary to hold your configuration values
config = {}    
# Call the function to load the config
load_config(keys)
client = OpenAI()
use_rag = False
use_snippets = False
only_links = False


if st.secrets["use_docker"] == "True" or check_password():
    
    if st.session_state['user_question']:
        if st.button('Clear input'):
            # Clear the input field by setting its value in session_state to an empty string
            st.session_state['user_question'] = ""
            
    user_prompt = st.text_input("Enter your question for your AI team here; press enter to update:", value=st.session_state['user_question'])

    # Update session_state with the input
    st.session_state['user_question'] = user_prompt



    improved_expander = False    
    if st.button("Improve my question!"):
        improved_expander = True
        try:
            improved_question = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": system_prompt_improve_question},
                    {"role": "user", "content": user_prompt}
                ],
                stream=False,
            )
        except:
            st.error("We have an error at OpenAI. Check https://status.openai.com.")
        st.session_state["improved_question"] = improved_question.choices[0].message.content
    # Display the response from the API.
    if st.session_state.improved_question:
        with st.expander("Your improved question:", expanded=improved_expander):
            st.text_area("Improved Question - edit below as needed. If editing, hit your CMD (or CTRL) + *return* key when done editing", st.session_state.improved_question, height=150, key="improved_question_text_area")
    col1, col2 = st.columns(2)
    with col1:
        use_internet = st.checkbox("Also search for evidence", value=True)
    with col2:
        use_original = st.checkbox("Check to send your original version.")
        if st.checkbox("Show Process Steps in Final Response"):
            updated_reconcile_prompt = reconcile_prompt.format(formatting = full_formatting)
        else:
            updated_reconcile_prompt = reconcile_prompt.format(formatting = short_formatting)

    
    
    if use_internet:
        
        with st.sidebar:
            search_method = st.radio("Web content used:", ("Just display links", "Web snippets from up to 10 webpages", "RAG (Retrieval-Augmented Generation) processing full-text from up to 5 webpages"), index = 1)
            with st.expander("Internet Search Details:"):
                if search_method == "RAG (Retrieval-Augmented Generation) processing full-text from up to 5 webpages":
                    scrape_method = st.radio("Web scraping method:", ("Browserless", "ScrapeNinja"))
                    use_rag = True
                    max = 5
                if search_method == "Web snippets from up to 10 webpages" or search_method == "Just display links":
                    use_snippets = True
                    max = 10
                if search_method == "Just display links":
                    only_links = True
                
                add_domains = st.checkbox("Add additional domains to search?")
                if add_domains:
                    domain_to_add = st.text_input("Enter additional domains to the list of options (e.g. www.cdc.gov OR www.nih.gov):",)
                    if st.button("Add domain"):
                        st.session_state.domain_list.insert(0, domain_to_add)
                
                domains_only = st.multiselect("Click after the last red one to see other options!", st.session_state.domain_list, default=default_domain_list)
        domains = ' OR '.join(['site:' + domain for domain in domains_only])
        if use_rag:
            st.warning("RAG is using on the fly web scraping and processing that may take a couple minutes for the final answer.")
        # st.write(domains)
        
        # with st.expander("Domains used with web search:"):
            
        #     for site in domain_list:
        #         st.write(site)

        # max = 4
        # if use_rag:
        #     max = 9
    begin = st.button("Ask your question!")    


    with st.sidebar.expander("Click to View Model Options:", expanded=False):
        st.markdown("[Model Explanations](https://openrouter.ai/models)")
        model1 = st.selectbox("Model 1 Options", ("openai/gpt-3.5-turbo", "openai/gpt-4-turbo", "anthropic/claude-3-sonnet", "anthropic/claude-instant-v1", "google/gemini-pro", "mistralai/mixtral-8x7b-instruct", "google/palm-2-chat-bison-32k", "openchat/openchat-7b", "phind/phind-codellama-34b", "meta-llama/llama-2-70b-chat", "meta-llama/llama-2-13b-chat", "gryphe/mythomax-L2-13b", "nousresearch/nous-hermes-llama2-13b", "undi95/toppy-m-7b"), index=0)
        model2 = st.selectbox("Model 2 Options", ("openai/gpt-3.5-turbo", "openai/gpt-4-turbo", "anthropic/claude-3-sonnet", "anthropic/claude-instant-v1", "google/gemini-pro", "mistralai/mixtral-8x7b-instruct", "google/palm-2-chat-bison-32k", "openchat/openchat-7b", "phind/phind-codellama-34b", "meta-llama/llama-2-70b-chat", "meta-llama/llama-2-13b-chat", "gryphe/mythomax-L2-13b", "nousresearch/nous-hermes-llama2-13b", "undi95/toppy-m-7b"), index=2)
        model3 = st.selectbox("Reconciliation Model 3 Options", ("gpt-3.5-turbo", "gpt-4-turbo"), index = 1)
        if use_rag:
            model4 = st.selectbox("RAG Model Options: Only OpenAI models (ADA for embeddings)", ("gpt-3.5-turbo", "gpt-4-turbo"), index=0)


    if begin:
        if use_original:
            st.session_state['final_question'] = user_prompt
        else:
            st.session_state['final_question'] = st.session_state.improved_question
        if use_internet:
            try:

                st.session_state.snippets, urls = realtime_search(user_prompt, domains, max)
                # st.session_state.snippets, urls = realtime_search(st.session_state.final_question, domains, max)

            except:
                st.error("Web search failed to respond; try again or uncheck internet searching.")
                st.session_state.snippets = ["Web search failed to respond.", "Try again or uncheck internet searching."]

        parallel_processing_question = st.session_state.final_question

        args1 = (prefix, '', '', parallel_processing_question, 0.4, '', model1, False)
        args2 = (prefix, '', '', parallel_processing_question, 0.4, '', model2, False)


        with concurrent.futures.ThreadPoolExecutor() as executor:
            future1 = executor.submit(answer_using_prefix, *args1)
            future2 = executor.submit(answer_using_prefix, *args2)
            # future3 = executor.submit(realtime_search, *args3)
     

        
            with st.spinner('Waiting for models to respond...'):    
            
                try:
                    model1_response = future1.result()
                    model1_final = f'{model1} response:\n\n{model1_response}'
                    time1 = datetime.datetime.now()  # capture current time when process 1 finishes
                    # st.session_state.model1_response = model1_final
                except:
                    st.error("Model 1 failed to respond; consider changing.")
                    model1_final = "Model 1 failed to respond."
                
                try:
                    model2_response = future2.result()
                    model2_final = f'{model2} response:\n\n{model2_response}'
                    time2 = datetime.datetime.now()  # capture current time when process 2 finishes
                    # st.session_state.model2_response = model2_final
                except:
                    st.error("Model 2 failed to respond; consider changing.")
                    model2_final = "Model 2 failed to respond."

                # try:
                #     snippets, urls = future3.result()
                #     st.session_state.snippets = snippets
                #     time3 = datetime.datetime.now()  # capture current time when process 3 finishes

    
        st.session_state.model1_response = model1_final
        st.session_state.model2_response = model2_final

        with st.expander(f'Model 1 Response'):
            st.markdown(st.session_state.model1_response)
            

        with st.expander(f"Model 2 Response"):
            st.markdown(st.session_state.model2_response)
            
        if use_snippets and only_links == False:
            with st.expander(f"Web Snippets Sent to the LLM:"):
                for snip in st.session_state.snippets:
                    snip = snip.replace('<END OF SITE>', '\n\n')
                    st.markdown(snip)
                    st.session_state.ebm = snip


        if use_rag: 
            with st.spinner('Obtaining fulltext from web search results...'):
                if scrape_method != "Browserless":
                    # web_scrape_response = scrapeninja(urls, max) 
                    web_scrape_response = scrapeninja(urls, max) 
                if scrape_method == "Browserless":
                    web_scrape_response = browserless(urls, max)
                
                web_scrape_string = json_data_to_string(web_scrape_response)
                doc = Document(text=web_scrape_string, doc_id="Web Content")
                
                service_context = ServiceContext.from_defaults(llm=llamaOpenAI(model=model4, temperature=0.5, system_prompt="You are an expert at extracting accurate information from web content."))
                index = VectorStoreIndex.from_documents([doc], service_context=service_context)
                
                if "chat_engine" not in st.session_state.keys(): # Initialize the chat engine
                    st.session_state.chat_engine = index.as_chat_engine(chat_mode="condense_question", verbose=False)
                
                response = st.session_state.chat_engine.chat(st.session_state.final_question)
                with st.expander('Sources and Generated Summary Using the Web:'):          
                    st.write("These are the sources used for the RAG model:")
                    for url in urls:
                        st.write(url)
                    st.write("Here is the answer according to the RAG processed web content:")    
                    st.markdown(response.response)
                    st.session_state.ebm = response.response
                    
        if only_links:
            with st.expander(f"Additional Links for you!"):
                st.warning("These are not sent to the LLM with this 'Links Only' option and appear here for your review.")
                for snip in st.session_state.snippets:
                    snip = snip.replace('<END OF SITE>', '\n\n')
                    st.markdown(snip)
            


        # if use_rag and st.session_state.ebm != '':
        #     # with st.expander('Content retrieved from the RAG model:'):
        #     with st.expander('Evidence Summary sent to the LLM:'):
        #         st.markdown(st.session_state.ebm)   
                       
        if use_snippets and only_links == False:   
            web_addition = st.session_state.ebm
        elif use_rag:
            web_addition = st.session_state.ebm
        else:
            web_addition = ''       

        final_answer = reconcile(st.session_state.final_question, model3, f'A {model1} response was:\n\n{st.session_state.model1_response}', f'A {model2} response was:\n\n{st.session_state.model2_response}', f'Information from the web was:\n\n{web_addition}', updated_reconcile_prompt)
        st.session_state.final_response = f'Submitted Question: {st.session_state.final_question}  \n\nReconciled Response from {model3}\n\n{final_answer}'
        # st.markdown(st.session_state.final_response)
        html = markdown2.markdown(final_answer, extras=["tables"])
        st.download_button('Download Reconciled Response', html, f'final_response.html', 'text/html')
    
    with st.sidebar:
        st.header('Download and View Last Reponses')
        st.write('Updating parameters on the main page resets outputs, so view prior results here.')
        if st.session_state.model1_response != '':
            with st.expander(f'Model 1 Response'):
                st.write(st.session_state.model1_response)
                st.download_button('Download Model1 Summary', st.session_state.model1_response, f'model1.txt', 'text/txt')
        if st.session_state.model2_response != '':        
            with st.expander(f"Model 2 Response"):
                st.write(st.session_state.model2_response)
                st.download_button('Download Model2 Summary', st.session_state.model2_response, f'model2.txt', 'text/txt')
        if st.session_state.ebm != '':
            with st.expander('Content retrieved from the RAG model'):
                st.markdown(st.session_state.ebm)  
                st.download_button('Download RAG Evidence Summary', st.session_state.ebm, f'rag.txt', 'text/txt')
        if use_internet:
            if use_snippets:
                with st.expander(f"Web Search Content:"):                
                    st.markdown("Web Snippets:")
                    for snip in st.session_state.snippets:
                        cleaned_snip = snip.replace("<END OF SITE>", "")  # Remove "<END OF SITE>" from the snippet
                        st.markdown(cleaned_snip) 
                    st.download_button('Download Web Snippets', str(st.session_state.snippets), f'web_snips.txt', 'text/txt')
        if st.session_state.final_response != '':        
            with st.expander(f"Current Consensus Response"):
                st.write(st.session_state.final_response)
                if len(st.session_state.thread) == 0 or st.session_state.thread[-1] != st.session_state.final_response:
                    st.session_state.thread.append(st.session_state.final_response)
                st.download_button('Download Final Response', st.session_state.final_response, f'final_response.txt', 'text/txt')

        st.write("_______")
        if st.session_state.thread != []:        
            with st.expander(f"Saved Record of Consensus Responses"):
                convo_str = ''
                convo_str = "\n\n________\n\n________\n\n".join(st.session_state.thread)
                st.markdown(convo_str)
                html = markdown2.markdown(convo_str, extras=["tables"])
                st.download_button('Download Conversation Record', html, f'convo.html', 'text/html')

                    

                
    st.markdown(st.session_state.final_response)
    
    if st.checkbox("Enter a follow-up question number or ask your own follow-up question."):
    
        final_followup_prompt = f'{followup_system_prompt} Question was:\n\n{user_prompt} \n\n Answer was {st.session_state.final_response}'
    

        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        

        if "messages" not in st.session_state:

            st.session_state.messages = [{"role": "system", "content": final_followup_prompt}]
            
        for message in st.session_state.messages:
            if message['role'] == "system":
                if message['content'] != final_followup_prompt:
                    st.session_state.messages = []
                    st.session_state.messages = [{"role": "system", "content": final_followup_prompt}]
                

        for message in st.session_state.messages:
            if message['role'] != "system":
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        if prompt := st.chat_input("Ask followup!"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                stream = client.chat.completions.create(
                    model=model3,
                    messages=[
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages
                    ],
                    stream=True,
                )
                response = st.write_stream(stream)
                html = markdown2.markdown(response, extras=["tables"])
                st.download_button('Download Followup Response', html, f'followup_response.html', 'text/html')
            st.session_state.messages.append({"role": "assistant", "content": response})