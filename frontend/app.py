import streamlit as st
from streamlit.logger import get_logger
import boto3
import json
import requests as req
import os
import uuid
import time
import pandas as pd
from langchain.agents import load_tools, initialize_agent, AgentType
from langchain.llms import Bedrock

logger = get_logger(__name__)

sample_audio_dir_path = "./sample-audio"

s3 = boto3.client('s3')
sm_client = boto3.client('stepfunctions')
bucket = os.environ['BucketName']
api_endpoint = os.environ['LLMAppAPIEndpoint']
bedrock_region = os.environ['BedrockRegion']

def get_llm():
    anthropic_model_kwargs = { #set parameters for an Anthropic model
        "max_tokens_to_sample": 1024, #maximum generated tokens
        "temperature": 0.2, #randomness of response, between 0 and 1
        "top_p": 0.9, #distribution of options
        "stop_sequences": ["\n\n Human:","\n\n Question:", "\nInstruction:"] #text that will stop the model from generating more text
    }

    llm = Bedrock(  #create a Bedrock llm client
        model_id="anthropic.claude-v1", #Bedrock will pass the request to Anthropic Claude
        model_kwargs=anthropic_model_kwargs,
        region_name=bedrock_region
    )

    return llm

def find_audio_files(directory):
    audio_files = []
    audio_absolute_path = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            audio_files.append(file)
            audio_absolute_path.append(os.path.join(root, file))
    
    logger.info(f"Found {len(audio_files)} audio files:")
    for audio_file in audio_files:
        logger.info(audio_file)
    logger.info(f"Absolute paths of audio files {audio_absolute_path}")
    return audio_files, audio_absolute_path

#upload audio file to S3 bucket
def upload_audio_start_summarization(audio_file, bucket, s3_file):

    logger.info(f"Uploading {audio_file} to {bucket}/{s3_file}")
    s3.upload_file(audio_file, bucket, s3_file)
    logger.info('Audio uploaded')
    ext = s3_file.split('.')[1]
    job_name = s3_file.split('/')[1].rstrip(f'.{ext}')
    job_name_list.append(job_name)
    job_uri = f"s3://{bucket}/{s3_file}"
    st.success('Starting Audio Analysis')
    return job_name_list, job_uri, bucket

#submit audio file for analysis
def submit_api_request(job_name, job_uri, bucket, language):
    output_prefix = 'audio_transcripts'
    data = {"job_name": job_name, "job_uri": job_uri, "output_location": bucket, "output_prefix": output_prefix, "language": language}
    headers = {"accept": "application/json", "Content-Type": "application/json"}
    resp = req.post(f"{api_endpoint}api", headers=headers, json=data)
    if resp.status_code == 200:
        output = resp.text
    else:
        st.error('Error submitting audio file for analysis')
        output = resp.text
    return output

languages = ['English']

st.set_page_config(page_title="Patient Chart Automation")
st.markdown("# Patient Chart Automation for Medical Providers")

audio_list, audio_list_path = find_audio_files(sample_audio_dir_path)

audio_mapping = {}
formatted_audio_name_list = []
for audio in audio_list:
    base_name = os.path.splitext(audio)[0]
    parts = base_name.split("_")
    capitalized_parts = [part.capitalize() for part in parts]
    formatted_audio_name = " ".join(capitalized_parts)
    formatted_audio_name_list.append(formatted_audio_name)
    audio_mapping[formatted_audio_name] = audio

formatted_audio_name_list.insert(0, "Select")

with st.sidebar:
    st.header("Patient Provider Conversations")
    audio_select = st.selectbox("**Sample Audio**", formatted_audio_name_list)

if audio_select != "Select":
    audio = audio_mapping[audio_select]
    if audio in audio_list:
        st.subheader("Play Audio")
        audio_file = open(audio_list_path[audio_list.index(audio)], 'rb')
        st.audio(audio_file, format='audio/wav')

        default_lang_ix = languages.index('English')
        st.subheader("Select an output language")
        language = st.selectbox(
            "Select an output language", options=languages, index=default_lang_ix)

        full_transcript = ''
        job_name_list = []
        if audio is not None:
            if 'wav' in audio or 'mp4' in audio or 'mp3' in audio:        
                st.success(audio_select + ' ready for analysis')
                if st.button('Start'):
                    with st.spinner('Starting Patient Chart Creation...'):
                        job_name_list, job_uri, output_location = upload_audio_start_summarization(audio_list_path[audio_list.index(audio)], bucket, f'audio_conversations/{str(uuid.uuid4())}-{audio}')
                    if job_name_list:
                        with st.spinner('Starting conversation analysis job..This should take a couple of seconds or minutes'):
                            response = json.loads(submit_api_request(job_name_list[0], job_uri, output_location, language))
                            try:
                                st.session_state.sm_exec_arn = response['sm_execution_arn']
                                response = sm_client.describe_execution(executionArn=st.session_state.sm_exec_arn)
                                status = response['status']
                                while status == 'RUNNING':
                                    logger.info("Still running, checking again...")
                                    time.sleep(5)
                                    response = sm_client.describe_execution(executionArn=st.session_state.sm_exec_arn)
                                    status = response['status']
                                if status == 'SUCCEEDED':
                                    response = json.loads(response['output'])['Outputs']
                                else:
                                    raise Exception(f"Step function failed with status: {response['status']}")
                                st.success('Conversation analysis completed and Patient Chart Creation Completed')
                                bedrock_output = response['BedrockOutput']['bedrock_model_result']
                                st.write("# Patient Chart Summary:\n", bedrock_output)
                                text, category, type, med_condition, = [], [], [], []
                                for entity in response['ComprehendMedicalOutput']['entities']:
                                    text.append(entity['Text'])
                                    category.append(entity['Category'])
                                    type.append(entity['Type'])
                                    if entity['Category'] == 'MEDICAL_CONDITION':
                                        med_condition.append(entity['Text'])
                                        _med_condition = '\n'.join(med_condition)
                                df = pd.DataFrame({'Text': text, 'Category': category, 'Type': type})
                                st.write("# Key Health Entities:", df)

                                if med_condition:
                                    logger.info(f"All Medical condition detected from conversation:\n{_med_condition}")
                                    llm = get_llm()
                                    tools = load_tools(['wikipedia'], llm=llm)

                                    agent = initialize_agent(
                                        tools,
                                        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
                                        verbose=True,
                                        llm=llm,
                                        handle_parsing_errors=True
                                    )
                                    # answer = ""
                                    # for condition in med_condition:
                                    #     response = agent.run(f"Provide a brief description of {condition}")
                                    #     condition_up = condition.upper()
                                    #     answer += f"{condition_up}:\n{response}\n\n"
                                    response = agent.run(f"""Based on this summary: \n {bedrock_output} \n Identify the key health condition the patient 
                                                         is diagnozed with and provide detailed description of the condition to educate the patient""")
                                    st.subheader("Patient Education")
                                    # st.write(answer)
                                    st.write(response)

                                else:
                                    logger.info("No medical condition detected from conversation")

                            except Exception as e:
                                logger.error(e)
                                st.error('Error submitting conversation for analysis')
                                st.stop()
                    else:
                        st.error('Error uploading audio file for analysis')
                        st.stop()
        else:
            st.failure('Incorrect file type provided. Please select a speech wav file or a mp3 or a mp4 file to proceed')





