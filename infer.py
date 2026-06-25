import boto3
from aws_detect import list_of_veggies

def classify_ingredients(image_path, region='ap-northeast-1', min_conf=80, top_k=3):
    client = boto3.client(
        'rekognition',
        region_name='ap-northeast-1',
        aws_access_key_id='AKIA2CTDMPS7WOYEGR6J',
        aws_secret_access_key='**********************'
    )

    with open(image_path, 'rb') as img:
        resp = client.detect_labels(Image={'Bytes': img.read()})
    
    matches = []
    for lab in resp['Labels']:
        name_en = lab['Name'].lower()
        conf = lab['Confidence']

        if name_en not in list_of_veggies:
            continue

        if conf >= min_conf:
            matches.append((name_en, conf))
            if len(matches) >= top_k:
                break
    for lab in resp['Labels']:
        print(f"⚠️ Rekognition 回傳：{lab['Name']} ({lab['Confidence']:.1f}%)")


    print("🔍 [infer] matches =", matches, flush=True)
    return matches