import pandas as pd

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import json
from employee_attrition.ml_logic.registry import load_model
from employee_attrition.ml_logic.data import get_clean_data_from_gcs, save_data_to_gcs, get_raw_data_from_gcs
from employee_attrition.interface.main import train_model
from employee_attrition import params

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.state.model = load_model()

@app.post("/predict")
def predict(File: UploadFile=File(...)):
    content = File.file.read()
    decode = content.decode('utf-8')
    df_json = json.loads(decode)
    X_pred = pd.DataFrame(df_json)
    print(X_pred)
    X_processed = app.state.preproc_pipe.transform(X_pred)
    print(X_processed)
    # Make prediction
    try:
        y_pred_proba = app.state.model.predict_proba(X_processed)
        # Assuming y_pred_proba is a single probability value for positive class
        positive_probability = float(y_pred_proba[0, 1])
        return {'probability_to_attend': positive_probability}
        # return app.state.model.predict(X_processed)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/predict")
def predict(
        pickup_datetime: str,  # 2014-07-06 19:18:00
        pickup_longitude: float,    # -73.950655
        pickup_latitude: float,     # 40.783282
        dropoff_longitude: float,   # -73.984365
        dropoff_latitude: float,    # 40.769802
        passenger_count: int
    ):      # 1
    """
    Make a single course prediction.
    Assumes `pickup_datetime` is provided as a string by the user in "%Y-%m-%d %H:%M:%S" format
    Assumes `pickup_datetime` implicitly refers to the "US/Eastern" timezone (as any user in New York City would naturally write)
    """
    # $CHA_BEGIN

    # 💡 Optional trick instead of writing each column name manually:
    # locals() gets us all of our arguments back as a dictionary
    # https://docs.python.org/3/library/functions.html#locals
    X_pred = pd.DataFrame(locals(), index=[0])

    # Convert to US/Eastern TZ-aware!
    X_pred['pickup_datetime'] = pd.Timestamp(pickup_datetime, tz='US/Eastern')

    model = app.state.model
    assert model is not None

    X_processed = preprocess_features(X_pred)
    y_pred = model.predict(X_processed)

    # ⚠️ fastapi only accepts simple Python data types as a return value
    # among them dict, list, str, int, float, bool
    # in order to be able to convert the api response to JSON
    return dict(fare=float(y_pred))
    # $CHA_END

# def predict(payload: dict):
#     """
#     Make a single prediction for binary classification.
#     """

#     # Check if all required columns are present in the payload
#     if not all(column in payload for column in COLUMN_NAMES_RAW):
#         raise HTTPException(status_code=400, detail="Missing required columns in payload")

#     # Convert payload to DataFrame
#     X_pred = pd.DataFrame({column: [payload.get(column, '')] for column in COLUMN_NAMES_RAW})

#     # Preprocess features if needed
#     X_processed = preprocess_features(X_pred)

#     # Make prediction
#     try:
#         # y_pred_proba = app.state.model.predict_proba(X_processed)
#         # Assuming y_pred_proba is a single probability value for positive class
#         positive_probability = 1 # float(y_pred_proba[0, 1])
#         return {'probability_to_attend': positive_probability}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))



@app.get("/")
def root():
    return {
        "greeting": "works!"
    }

@app.get("/getCleanData")
def getCleanData():
    # 1. Load the latest data files from google cloud storage
    # 2. Merge and clean the data
    # 3. Save the cleaned data on google cloud storage again for dashboard
    # 4. If everythin OK, return a OK message otherwise an appropriate error message

    ## Doing 1st and 2nd steps
    success, result = get_raw_data_from_gcs()

    if success:
        data_ml, data_analytics = result[0], result[1]

        ## Doing 3rd and 4th steps
        save_flag, message = save_data_to_gcs(data_ml, data_analytics)
        if save_flag :
            return {
                "Success" : "Cleaned Files saved in GCS, {message}"
            }
        else :
            return {
                "Error" : f"Unable to save the cleaned data in GCS, {message}"
            }
    else :
        return {
            "Error" : f"Unable to load file from GCS, {result}"
        }


# @app.get("/train_model")
# def train_model():
#     # 1. read the latest clean data from google cloud
#     # 2. preprocess it
#     # 3. train the model

#     success, message = train_model2(save=True)
#     if success:
#         model_dic = message
#         return {
#             "params" : model_dic['params'],
#             "score" : model_dic['score']
#         }

#     else :
#         return {
#             "Error" : f"Unable to train model, {message}"
#         }


@app.post("/get_similar_users")
def get_similar_users(File: UploadFile=File(...)):
    content = File.file.read()
    decode = content.decode('utf-8')
    df_json = json.loads(decode)
    X_pred = pd.DataFrame(df_json)

    print("Received the prediction data")
    print(X_pred)
    X_processed = app.state.preproc_pipe.transform(X_pred)
    print("Transformed the prediction data")
    print(X_processed)
    # Make prediction
    # breakpoint()
    try:
        if params.DATA_TARGET == 'local':
            print(" Reading the clean data from local folder: raw_data..")
            data_for_ml = pd.read_csv(f"raw_data/{params.CLEANED_FILE_ML}", index_col=0)

        elif params.DATA_TARGET == 'gcs':

            print("Reading the clean data from gcs ..")
            bucket_name = params.BUCKET_NAME
            gsfile_path_events_ppl = f'gs://{bucket_name}/{params.CLEANED_FILE_ML}'
            data_for_ml = pd.read_csv(gsfile_path_events_ppl)

        # Processed the training data
        X_train_processed = app.state.preproc_pipe.transform(data_for_ml)

        # Find the indices of similar user based on cosine_similarity
        user_id_indices = similar_users(X_train_processed, X_processed)

        # Get the user information and send it back as a json
        users_info = data_for_ml.iloc[user_id_indices][['jobTitle','company']]
        users_info.index = users_info.index.astype(int)

        # users_info.index.name = "User_ID"
        # users_info.reset_index(inplace= True)

        user_dict = users_info.to_json()
        print(user_dict)

        return user_dict

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
