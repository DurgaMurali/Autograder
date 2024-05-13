import subprocess
import time
from flask import Flask, render_template, request, redirect
import boto3
import os
import shutil
import hashlib

dynamodb = boto3.resource('dynamodb', region_name='us-west-1')
userTable = dynamodb.Table('users')
assignmentTable = dynamodb.Table('assignments')

app = Flask(__name__)

global assignment, user, email_id
assignment = {}
user = ""
email_id = ""

@app.route('/')
def index():  
    return render_template('index.html')

def hash_password(password):
   password_bytes = password.encode('utf-8')
   hash_object = hashlib.sha256(password_bytes)
   return hash_object.hexdigest()

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    if email.endswith('sjsu.edu'):
        db_response = userTable.get_item(Key={'email':email})
        if 'Item' in db_response:
                if 'password' in db_response['Item']:
                    password_db = db_response['Item']['password']
                    password_hashed = hash_password(password)
                    if password_db == password_hashed:
                        global email_id
                        email_id = email
                        if 'lastname' in db_response['Item']:
                            global user
                            user = db_response['Item']['lastname']
                        if email == 'admin@sjsu.edu':
                            return redirect('/create-assignment')
                        else:
                            return redirect('/view-assignment')
                    else:
                        return render_template('index.html', message="Invalid Email/Password")
        else:
            return render_template('index.html', message="User not registered")
    else:
        return render_template('index.html', message="Enter SJSU Email ID")

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register_user():
    email = request.form.get('email')
    sjsu_id = request.form.get('sjsu_id')
    firstname = request.form.get('firstname')
    lastname = request.form.get('lastname')
    password_1 = request.form.get('password_1')
    password_2 = request.form.get('password_2')

    # Password and re-entered password do not match
    if(password_1 != password_2):
        return render_template('register.html', message="Passwords do not match. Register again!")
    
    # User already exists
    db_response = userTable.get_item(Key={'email':email})
    if 'Item' in db_response:
        return render_template('index.html', message="User already exists, Login!")
    else:
        password_hashed = hash_password(password_1)
        db_response = userTable.put_item(
        Item={
            'email': str(email),
            'sjsu_id': str(sjsu_id),
            'firstname': str(firstname),
            'lastname': str(lastname),
            'password': str(password_hashed),
            'score': str(0)
        })
        return render_template('index.html')

def get_assignments():
    db_response = assignmentTable.scan()
    global assignment
    if 'Items' in db_response:
        for item in db_response['Items']:
            assignment = item
            break
    #print(assignment)

@app.route('/view-assignment')
def view_assignment():
    get_assignments()
    global assignment
    if 'assignment_name' in assignment:
        problem_name = assignment['assignment_name']
        problem = assignment['assignment_description']
        return render_template('assignment_submission.html', problem_name=problem_name, problem=problem)
    else:
        return render_template('score.html', no_assignment_message="No Assignments. Rest up!")

@app.route('/submit-assignment', methods=['POST'])
def submit_assignment():
    file = request.files.get('assignment-file')
    code = request.form.get('code')

    folder_name = "Assignment_Submissions_" + user
    folder_path = os.path.join(os.path.dirname(__file__), folder_name)
    #print(folder_path)

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    if code:
        file_path = "{path}/{file}".format(path=folder_path, file='submission.py')
        with open(file_path, 'w') as f:
            f.write(code)

    elif file:
        file_path = "{path}/{file}".format(path=folder_path, file=file.filename)
        try:
            file.save(file_path)
        except IOError as e:
            print(e)

    submission_score, kept_score, messages = autograde(folder_path, file_path)
    os.remove(file_path)
    os.rmdir(folder_path)
    submission_score_msg = "Submission score : " + str(submission_score)
    kept_score_msg = "Kept score : " + str(kept_score)
    return render_template('score.html', submission_score=submission_score_msg, kept_score=kept_score_msg, results=messages)

def read_program_file(filename) -> str:
    with open(filename) as f:
        file = f.read()
    return file

def autograde(folder_path, assignment_file_path):
    program = read_program_file(assignment_file_path)
    global assignment
    test = assignment['test_cases']

    code_file = folder_path + '/code.py'
    run_file = folder_path + '/run.py'
    with open(code_file, 'w') as f:
        f.write(program)
        f.write("\n" + test)

    passed_cases = 0
    total_cases = 0
    failed = False
    messages = []
    for index in range(1, 11):
        formatted_number = str(index).zfill(2)
        testcase = "testcase_" + str(formatted_number)
        if assignment[testcase] != "":
            test_name = assignment[testcase]
            total_cases += 1
            source_file = open(code_file, 'r')
            destination_file = open(run_file, 'w')
            shutil.copyfileobj(source_file, destination_file)
            destination_file.write("\n" + test_name + "()")
            source_file.close()
            destination_file.close()

            try:
                start = time.time()
                result = subprocess.run(["python3", run_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True, timeout=2)
                end = time.time()
                passed_cases += 1
                message = test_name + " [PASS] " + str(round((end - start)*1000, 2)) + "ms"
                print(message)
                messages.append(message)
            except subprocess.CalledProcessError as exc:
                print(f"Returned {exc.returncode}\n{exc}")
                print(exc.output)
                if("AssertionError" in exc.output):
                    message = test_name + " [FAIL] " + "Assertion Error"
                    messages.append(message)
                    print("Assertion Error")
                else:
                    message = test_name + " [FAIL] " + "Compiler Error"
                    messages.append(message)
                    failed = True
            except subprocess.TimeoutExpired as exc:
                print(f"Process timed out.\n{exc}")
                message = test_name + " [FAIL] " + "Time out Error"
                messages.append(message)
                failed = True

            os.remove(run_file)

        if failed == True:
            break
    
    os.remove(code_file)

    score = float(0.0)
    if failed == False:
        score = float((passed_cases/total_cases) * 100)
    print(score)

    db_response = userTable.get_item(Key={'email':email_id})
    if 'Item' in db_response:
        if 'score' in db_response['Item']:
            old_score = db_response['Item']['score']
            old_score = float(old_score)

            if score > old_score:
                userTable.update_item(
                    Key={'email': email_id},
                    AttributeUpdates={'score': {'Value': str(score), 'Action': 'PUT'}}
                )
                return (score, score, messages)
            else:
                return (score, old_score, messages)
            
    return (score, score, messages)

@app.route('/create-assignment')
def create_assignmnet():
    return render_template("assignment_upload.html")

@app.route('/upload-assignment', methods=['POST'])
def upload_assignment():
    assignment_name = request.form.get('assignment_name')
    assignment = request.form.get('assignment')
    test = request.form.get('test')
    testcase_01 = request.form.get('testcase_01')
    tc_01_desc = request.form.get('tc_01_desc')
    testcase_02 = request.form.get('testcase_02')
    tc_02_desc = request.form.get('tc_02_desc')
    testcase_03 = request.form.get('testcase_03')
    tc_03_desc = request.form.get('tc_03_desc')
    testcase_04 = request.form.get('testcase_04')
    tc_04_desc = request.form.get('tc_04_desc')
    testcase_05 = request.form.get('testcase_05')
    tc_05_desc = request.form.get('tc_05_desc')
    testcase_06 = request.form.get('testcase_06')
    tc_06_desc = request.form.get('tc_06_desc')
    testcase_07 = request.form.get('testcase_07')
    tc_07_desc = request.form.get('tc_07_desc')
    testcase_08 = request.form.get('testcase_08')
    tc_08_desc = request.form.get('tc_08_desc')
    testcase_09 = request.form.get('testcase_09')
    tc_09_desc = request.form.get('tc_09_desc')
    testcase_10 = request.form.get('testcase_10')
    tc_10_desc = request.form.get('tc_10_desc')

    db_response = assignmentTable.put_item(
        Item={
            'assignment_name': str(assignment_name),
            'assignment_description': str(assignment),
            'test_cases': str(test),
            'testcase_01': str(testcase_01),
            'testcase_01_description': str(tc_01_desc),
            'testcase_02': str(testcase_02),
            'testcase_02_description': str(tc_02_desc),
            'testcase_03': str(testcase_03),
            'testcase_03_description': str(tc_03_desc),
            'testcase_04': str(testcase_04),
            'testcase_04_description': str(tc_04_desc),
            'testcase_05': str(testcase_05),
            'testcase_05_description': str(tc_05_desc),
            'testcase_06': str(testcase_06),
            'testcase_06_description': str(tc_06_desc),
            'testcase_07': str(testcase_07),
            'testcase_07_description': str(tc_07_desc),
            'testcase_08': str(testcase_08),
            'testcase_08_description': str(tc_08_desc),
            'testcase_09': str(testcase_09),
            'testcase_09_description': str(tc_09_desc),
            'testcase_10': str(testcase_10),
            'testcase_10_description': str(tc_10_desc)
        }
    )
    return render_template('congratulations.html')


if __name__ == '__main__':
    app.run(host=os.getenv('IP', '0.0.0.0'), port=int(os.getenv('PORT', 9001)))