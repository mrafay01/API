import eventlet
eventlet.monkey_patch()

import base64
import datetime
import os
from flask import Flask, current_app, jsonify, request, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import date, datetime, timedelta
from flask_cors import CORS
from sqlalchemy.exc import SQLAlchemyError
import traceback
import random
import string
from flask_socketio import SocketIO, emit, join_room, leave_room

# If you installed via pip
# from agora_token_builder import RtcTokenBuilder
# If you copied the file
from agora_token_builder import RtcTokenBuilder

app = Flask("QuranAPI")
socketio = SocketIO(app, cors_allowed_origins="*")

CORS(app)

# Configure the SQL Server database connection
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "mssql+pyodbc://sa:123@DESKTOP-1TTIBM1\\MRAFE01/QURAN_TUTOR_DB?driver=ODBC+Driver+17+for+SQL+Server&multiple_active_result_sets=true"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app, engine_options={"isolation_level": "AUTOCOMMIT"})

AGORA_APP_ID = "your-app-id"
AGORA_APP_CERTIFICATE = "your-app-certificate"

@app.route("/GetStudent", methods=["GET"])
def appuser():
    return jsonify("Hassan"), 200


@app.route("/GetAllstudents", methods=["GET"])
def get_users():
    rows = db.session.execute(text("SELECT * FROM Student"))
    rw = []
    keys = ["id", "username", "name", "password", "region", "gender", "dob", "pic"]
    for row in rows:
        rw.append(dict(zip(keys, row)))
    return jsonify(rw), 200


@app.route("/GetAllTeachers", methods=["GET"])
def get_teachers():
    query = """
        SELECT 
            t.id AS T_id,
            t.username,
            t.name,
            t.password,
            t.cnic,
            t.region,
            t.qualification,
            t.gender,
            t.dob,
            t.pic,
            t.ratings,
            t.hourly_rate,
            t.bio,
            STRING_AGG(tl.Languages, ', ') AS Languages
        FROM Teacher t
        LEFT JOIN Teacher_Languages tl ON t.id = tl.TeacherID
        GROUP BY 
            t.id, t.username, t.name, t.password, t.cnic, t.region,
            t.qualification, t.gender, t.dob, t.pic, t.ratings,
            t.hourly_rate, t.bio
    """
    rows = db.session.execute(text(query))
    keys = [
        "id",
        "username",
        "name",
        "password",
        "cnic",
        "region",
        "qualification",
        "gender",
        "dob",
        "pic",
        "ratings",
        "hourly_rate",
        "bio",
        "languages",
    ]
    teachers = [dict(zip(keys, row)) for row in rows]

    # For each teacher, fetch canTeach and available
    for teacher in teachers:
        teacher_id = teacher["id"]
        # canTeach: list of course names
        courses = db.session.execute(text("""
            SELECT c.name FROM TeacherCourse tc JOIN Course c ON tc.course_id = c.id WHERE tc.qari_id = :tid
        """), {"tid": teacher_id}).fetchall()
        teacher["canTeach"] = [c[0] for c in courses]
        # available: list of {day, time, course} for unbooked slots
        slots = db.session.execute(text("""
            SELECT ts.day, s.time, c.name as course_name FROM TeacherSchedule ts JOIN Slot s ON ts.id = s.sch_id LEFT JOIN Course c ON s.Course_id = c.id WHERE ts.teacher_id = :tid AND s.booked = 0
        """), {"tid": teacher_id}).fetchall()
        teacher["available"] = [{"day": s[0], "time": s[1], "course": s[2]} for s in slots]

    return jsonify(teachers), 200


@app.route("/SignUpStudents", methods=["POST"])
def SignupStudent():
    body = request.json
    print(body)
    name = body.get("name", "def")
    dob = body.get("dob", "def")
    username = body.get("username", "def")
    region = body.get("region", "def")
    password = body.get("password", "def")
    gender = body.get("gender", "def")
    pic = body.get("pic")
    pic_path = None
    languages = body.get("languages", [])  # list of strings
    print("RAW pic value:", pic)
    if pic and pic != "def" and len(pic) > 30:
        try:
            header, encoded = pic.split(",", 1) if "," in pic else ("", pic)
            img_bytes = base64.b64decode(encoded)
            img_dir = os.path.join(current_app.root_path, "static", "profile_images")
            os.makedirs(img_dir, exist_ok=True)
            filename = f"{username}_profile.png"
            file_path = os.path.join(img_dir, filename)
            with open(file_path, "wb") as f:
                f.write(img_bytes)
            pic_path = f"/static/profile_images/{filename}"
            print(f"Image saved at: {pic_path}")
        except Exception as e:
            print("Image save failed:", e)
            return jsonify({"error": "Failed to save image", "details": str(e)}), 500
    else:
        print("No valid image provided.")
    check_query = text(f"SELECT COUNT(*) FROM Student WHERE username = :username")
    result = db.session.execute(check_query, {"username": username}).scalar()
    if result > 0:
        return (
            jsonify(
                {"error": "Username already taken, please try a different username"}
            ),
            409,
        )
    else:
        query = text(
            "INSERT INTO Student (username, name, password, region, gender, dob, pic) VALUES (:username, :name, :password, :region, :gender, :dob, :pic)"
        )
        try:
            db.session.execute(
                query,
                {
                    "username": username,
                    "name": name,
                    "password": password,
                    "region": region,
                    "gender": gender,
                    "dob": dob,
                    "pic": pic_path,
                },
            )
            db.session.commit()
            # Insert languages for student
            student_id = db.session.execute(
                text("SELECT id FROM Student WHERE username = :username"),
                {"username": username}
            ).scalar()
            for lang in languages:
                db.session.execute(
                    text("INSERT INTO StudentLanguages (S_id, Languages) VALUES (:student_id, :lang)"),
                    {"student_id": student_id, "lang": lang}
                )
            db.session.commit()
            return jsonify({"message": "Inserted Data"}), 201
        except Exception as e:
            print(e)
            db.session.rollback()
            return jsonify({"error": "Database insert failed", "details": str(e)}), 500


@app.route("/SignupParent", methods=["POST"])
def SignUpParent():
    body = request.json
    print(body)

    name = body.get("name", "def")
    region = body.get("region", "def")
    cnic = body.get("cnic", "def")
    username = body.get("username", "def")
    password = body.get("password", "def")
    student_username = body.get("student_username", "def")
    pic = body.get("pic")
    pic_path = None

    print("RAW pic value:", pic)

    if pic and pic != "def" and len(pic) > 30:
        try:
            header, encoded = pic.split(",", 1) if "," in pic else ("", pic)
            img_bytes = base64.b64decode(encoded)

            img_dir = os.path.join(current_app.root_path, "static", "profile_images")
            os.makedirs(img_dir, exist_ok=True)

            filename = f"{username}_profile.png"
            file_path = os.path.join(img_dir, filename)

            with open(file_path, "wb") as f:
                f.write(img_bytes)

            pic_path = f"/static/profile_images/{filename}"
            print(f"Image saved at: {pic_path}")
        except Exception as e:
            print("Image save failed:", e)
            return jsonify({"error": "Failed to save image", "details": str(e)}), 500
    else:
        print("No valid image provided.")

    # 1. Check if username already exists
    check_query = text("SELECT COUNT(*) FROM Parent WHERE username = :username")
    result = db.session.execute(check_query, {"username": username}).scalar()

    if result > 0:
        return (
            jsonify(
                {"error": "Username already taken, please try a different username"}
            ),
            409,
        )

    # 2. Check if student exists
    student_exists = db.session.execute(
        text("SELECT COUNT(*) FROM Student WHERE username = :student_username"),
        {"student_username": student_username}
    ).scalar()
    if student_exists == 0:
        return jsonify({"error": "Student username does not exist"}), 404

    # 3. Insert into Parent table (no student_ID)
    if pic_path:
        insert_query = text(
            "INSERT INTO Parent (name, cnic, username, password, region, pic) "
            "VALUES (:name, :cnic, :username, :password, :region, :pic)"
        )
        params = {
            "name": name,
            "cnic": cnic,
            "username": username,
            "password": password,
            "region": region,
            "pic": pic_path,
        }
    else:
        insert_query = text(
            "INSERT INTO Parent (name, cnic, username, password, region) "
            "VALUES (:name, :cnic, :username, :password, :region)"
        )
        params = {
            "name": name,
            "cnic": cnic,
            "username": username,
            "password": password,
            "region": region,
        }

    try:
        db.session.execute(insert_query, params)
        db.session.commit()
    except Exception as err:
        print(err)
        db.session.rollback()
        return jsonify({"error": "Database insert failed", "details": str(err)}), 500

    # 4. Get new parent id
    parent_id = db.session.execute(
        text("SELECT id FROM Parent WHERE username = :username"),
        {"username": username}
    ).scalar()

    # 5. Update Student(s) with this parent_id
    update_query = text(
        "UPDATE Student SET parent_id = :parent_id WHERE username = :student_username"
    )
    db.session.execute(update_query, {"parent_id": parent_id, "student_username": student_username})
    db.session.commit()
    return jsonify({"message": "Data has been inserted"}), 201


@app.route("/SignupTeacher", methods=["POST"])
def SignupTeacher():
    body = request.json
    name = body.get("name", "def")
    username = body.get("username", "def")
    region = body.get("region", "def")
    password = body.get("password", "def")
    gender = body.get("gender")
    if gender not in ("M", "F"):
        return jsonify({"error": "Invalid gender value"}), 400
    qualification = body.get("qualification", "def")
    cnic = body.get("cnic", "def")
    dob = body.get("dob", "def")
    pic = body.get("pic")
    pic_path = None
    languages = body.get("languages", [])  # list of strings
    # Handle image upload (same as before)
    if pic and len(pic) > 30:
        try:
            header, encoded = pic.split(",", 1) if "," in pic else ("", pic)
            img_bytes = base64.b64decode(encoded)
            img_dir = os.path.join(current_app.root_path, "static", "profile_images")
            os.makedirs(img_dir, exist_ok=True)
            filename = f"{username}_profile.png"
            file_path = os.path.join(img_dir, filename)
            with open(file_path, "wb") as f:
                f.write(img_bytes)
            pic_path = f"/static/profile_images/{filename}"
        except Exception as e:
            return jsonify({"error": "Failed to save image", "details": str(e)}), 500
    # Check duplicate username
    check_query = text("SELECT COUNT(*) FROM Teacher WHERE username = :username")
    result = db.session.execute(check_query, {"username": username}).scalar()
    if result > 0:
        return jsonify({"error": "Username already taken"}), 409
    # Insert Teacher (only basic info, set hourly_rate, SampleClip, etc. to NULL/default)
    insert_query = text(
        """
    INSERT INTO Teacher (username, name, password, cnic, region, qualification, gender, dob, pic, ratings, hourly_rate, bio, SampleClip)
    VALUES (:username, :name, :password, :cnic, :region, :qualification, :gender, :dob, :pic, 0, NULL, NULL, NULL)
                        """
    )
    try:
        db.session.execute(
            insert_query,
            {
                "username": username,
                "name": name,
                "password": password,
                "cnic": cnic,
                "region": region,
                "qualification": qualification,
                "gender": gender,
                "dob": dob,
                "pic": pic_path,
            },
        )
        db.session.commit()
        # Insert languages for teacher
        teacher_id = db.session.execute(
            text("SELECT id FROM Teacher WHERE username = :username"),
            {"username": username}
        ).scalar()
        for lang in languages:
            db.session.execute(
                text("INSERT INTO Teacher_Languages (TeacherID, Languages) VALUES (:teacher_id, :lang)"),
                {"teacher_id": teacher_id, "lang": lang}
            )
        db.session.commit()
    except Exception as e:
        print("Teacher insertion failed:", e)
        db.session.rollback()
        return jsonify({"error": "Teacher insertion failed", "details": str(e)}), 501
    return jsonify({"message": "Teacher registered successfully"}), 201


@app.route("/SignUpTeacherExtra", methods=["POST"])
def SignUpTeacherExtra():
    body = request.json
    username = body.get("username")
    hourly_rate = body.get("hourly_rate")
    courses = body.get("courses", [])  # list of strings
    sample_clip = body.get("sample_clip", None)
    # Save the video sample (optional, you can store as file or in DB)
    sample_clip_path = None
    if sample_clip and len(sample_clip) > 30:
        try:
            header, encoded = (
                sample_clip.split(",", 1) if "," in sample_clip else ("", sample_clip)
            )
            video_bytes = base64.b64decode(encoded)
            video_dir = os.path.join(current_app.root_path, "static", "teacher_samples")
            os.makedirs(video_dir, exist_ok=True)
            filename = f"{username}_sample.mp4"
            file_path = os.path.join(video_dir, filename)
            with open(file_path, "wb") as f:
                f.write(video_bytes)
            sample_clip_path = f"/static/teacher_samples/{filename}"
        except Exception as e:
            return jsonify({"error": "Failed to save video", "details": str(e)}), 500
    # Update teacher's hourly_rate and sample_clip in DB
    try:
        db.session.execute(
            text(
                "UPDATE Teacher SET hourly_rate = :hourly_rate, SampleClip = :sample_clip WHERE username = :username"
            ),
            {
                "hourly_rate": hourly_rate,
                "sample_clip": sample_clip_path,
                "username": username,
            },
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return (
            jsonify({"error": "Failed to update teacher profile", "details": str(e)}),
            500,
        )
    # Insert courses (if you have a Teacher_Courses table)
    teacher_id = db.session.execute(
        text("SELECT id FROM Teacher WHERE username = :username"),
        {"username": username},
    ).scalar()
    for course in courses:
        course_id = db.session.execute(
        text("SELECT id FROM Course WHERE name = :course"),
        {"course": course}
        ).scalar()
        if course_id:
            db.session.execute(
            text(
                "INSERT INTO TeacherCourse (qari_id, course_id) VALUES (:teacher_id, :course_id)"
            ),
            {"teacher_id": teacher_id, "course_id": course_id},
        )
    db.session.commit()
    # Add schedule (days and slots)
    schedule = body.get("schedule", [])
    for entry in schedule:
        day = entry.get("day")
        slots = entry.get("slots", [])
        course_name = entry.get("course")  # Course for slot is optional
        course_id = None
        if course_name:
            course_id = db.session.execute(
                text("SELECT id FROM Course WHERE name = :course"),
                {"course": course_name}
            ).scalar()
        # If course_id is None, use a default (e.g., 1) or NULL if allowed by DB
        for slot_time in slots:
            # Fetch or create TeacherSchedule for this teacher and day
            sch = db.session.execute(
                text("SELECT id FROM TeacherSchedule WHERE teacher_id = :tid AND day = :day"),
                {"tid": teacher_id, "day": day}
            ).fetchone()
            if not sch:
                sch_id = db.session.execute(
                    text("INSERT INTO TeacherSchedule (day, teacher_id) OUTPUT inserted.id VALUES (:day, :tid)"),
                    {"day": day, "tid": teacher_id}
                ).scalar()
            else:
                sch_id = sch.id
            db.session.execute(
                text("INSERT INTO Slot (time, sch_id, booked) VALUES (:time, :sch_id, 0)"),
                {"time": slot_time, "sch_id": sch_id}
            )
    db.session.commit()
    return jsonify({"message": "Teacher profile completed"}), 201


@app.route("/GetStudentByUsername", methods=["GET"])
def GetStudentByUsername():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    rows = db.session.execute(text(f"SELECT * FROM Student WHERE username='{username}'"))
    rw = []
    keys = [
        "id",
        "username",
        "name",
        "password",
        "region",
        "gender",
        "dob",
        "pic",
        "parent_id",
    ]
    for row in rows:
        rw.append(dict(zip(keys, row)))

    return jsonify(rw), 200


# from sqlalchemy import text


@app.route("/UpdateStudentByUsername", methods=["POST"])
def UpdateStudentByUsername():
    username = request.args.get("username")

    if not username:
        return jsonify({"error": "Username is required"}), 400

    data = request.json
    firstname = data.get("firstname", "Def")
    lastname = data.get("lastname", "Def")
    spic = data.get("spic", "Def")
    region = data.get("region", "Def")
    psw = data.get("psw", "Def")

    try:
        query = text(
            """
            UPDATE Student
            SET fname = :firstname,
                lname = :lastname,
                pic = :spic,
                region = :region,
                psw = :psw
            WHERE username = :username
        """
        )
        db.session.execute(
            query,
            {
                "firstname": firstname,
                "lastname": lastname,
                "spic": spic,
                "region": region,
                "psw": psw,
                "username": username,
            },
        )
        db.session.commit()

        return jsonify({"message": "Student information updated successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# @app.route("/DeleteStudentByUsername", methods=["DELETE"])
# def DeleteStudentByUsername():
#     username = request.args.get("username")

#     if not username:
#         return jsonify({"error": "Username is required"}), 400

#     try:
#         # Check if the student exists
#         student = db.session.execute(
#             text("SELECT * FROM Student WHERE username = :username"),
#             {"username": username},
#         ).fetchone()

#         if not student:
#             return jsonify({"error": "Student not found"}), 404

#         # Delete the student
#         query = text("DELETE FROM Student WHERE username = :username")
#         db.session.execute(query, {"username": username})
#         db.session.commit()

#         return (
#             jsonify(
#                 {"message": f"Student with username '{username}' deleted successfully"}
#             ),
#             200,
#         )

#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


# LOGINS


@app.route("/LoginTeacher", methods=["POST"])
def LoginTeacher():
    # Retrieve username and password from query parameters
    body = request.get_json()
    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    try:
        # Query the database to verify the username and password
        query = text(
            """
            SELECT * FROM Teacher 
            WHERE username = :username AND password = :password
        """
        )
        result = db.session.execute(
            query, {"username": username, "password": password}
        ).fetchone()

        if result:
            # If a match is found, return success
            return jsonify({"message": "Login successful", "username": username}), 200
        else:
            # If no match is found, return error
            return jsonify({"error": "Invalid username or password"}), 401

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/LoginStudent", methods=["POST"])
def LoginStudent():
    body = request.get_json()
    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    try:
        query = text(
            """
            SELECT * FROM Student 
            WHERE username = :username AND password = :password
            """
        )
        result = db.session.execute(
            query, {"username": username, "password": password}
        ).fetchone()

        if result:
            return jsonify({"message": "Login successful", "username": username}), 200
        else:
            return jsonify({"error": "Invalid username or password"}), 401

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/LoginParent", methods=["POST"])
def LoginParent():
    # Retrieve username and password from query parameters
    body = request.get_json()
    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    try:
        # Query the database to verify the username and password
        query = text(
            """
            SELECT * FROM Parent 
            WHERE username = :username AND password = :password
        """
        )
        result = db.session.execute(
            query, {"username": username, "password": password}
        ).fetchone()

        if result:
            # If a match is found, return success
            return jsonify({"message": "Login successful", "username": username}), 200
        else:
            # If no match is found, return error
            return jsonify({"error": "Invalid username or password"}), 401

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/GetParentProfile", methods=["GET"])
def GetParentProfile():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get parent id
    parent = db.session.execute(
        text("SELECT id, name, region, cnic, username FROM Parent WHERE username = :username"),
        {"username": username}
    ).fetchone()
    if not parent:
        return jsonify({"error": "Parent not found"}), 404

    # Get all students for this parent
    students = db.session.execute(
        text("SELECT id, username, name, gender, dob, region, pic FROM Student WHERE parent_id = :parent_id"),
        {"parent_id": parent.id}
    ).fetchall()
    students_list = [dict(row._mapping) for row in students]

    print("[GetParentProfile] Children data:", students_list)

    data = dict(parent._mapping)
    data["role"] = "Parent"
    data["children"] = students_list
    return jsonify(data), 200


@app.route("/GetParentDashboard", methods=["GET"])
def GetParentDashboard():
    username = request.args.get("username")

    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get Parent ID
    parent_result = db.session.execute(text("""
        SELECT id FROM Parent WHERE username = :username
    """), {"username": username}).fetchone()

    if not parent_result:
        return jsonify({"error": "Parent not found"}), 404

    parent_id = parent_result.id
    result = {}

    # Total Children
    result["totalChildren"] = db.session.execute(text("""
        SELECT COUNT(*) FROM Student WHERE parent_id = :parent_id
    """), {"parent_id": parent_id}).scalar()

    # Active Courses
    result["activeCourses"] = db.session.execute(text("""
        SELECT COUNT(DISTINCT e.course_id)
        FROM Enrollment e
        JOIN Student s ON e.student_id = s.id
        WHERE s.parent_id = :parent_id
    """), {"parent_id": parent_id}).scalar()

    # Total Hours This Month
    result["totalHoursThisMonth"] = db.session.execute(text("""
        SELECT COALESCE(SUM(DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime)), 0) / 60.0
        FROM VideoCallSession v
        JOIN Student s ON v.StudentID = s.id
        WHERE s.parent_id = :parent_id
        AND MONTH(v.CallStartTime) = MONTH(GETDATE())
        AND YEAR(v.CallStartTime) = YEAR(GETDATE())
    """), {"parent_id": parent_id}).scalar()

    # Monthly Spending (assumes teacher hourly_rate × hours)
    result["monthlySpending"] = round(db.session.execute(text("""
        SELECT COALESCE(SUM(DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) * t.hourly_rate / 60.0), 0)
        FROM VideoCallSession v
        JOIN Student s ON v.StudentID = s.id
        JOIN Teacher t ON v.TeacherID = t.id
        WHERE s.parent_id = :parent_id
        AND MONTH(v.CallStartTime) = MONTH(GETDATE())
        AND YEAR(v.CallStartTime) = YEAR(GETDATE())
    """), {"parent_id": parent_id}).scalar(), 2)

    # Children Data
    children_data = db.session.execute(text("""
        SELECT 
            s.id,
            s.name,
            s.pic AS avatar,
            DATEDIFF(YEAR, s.dob, GETDATE()) AS age,
            (
                SELECT COUNT(DISTINCT e.course_id)
                FROM Enrollment e
                WHERE e.student_id = s.id
            ) AS coursesEnrolled,
            (
                SELECT COALESCE(SUM(DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime)), 0) / 60.0
                FROM VideoCallSession v
                WHERE v.StudentID = s.id AND DATEDIFF(DAY, v.CallStartTime, GETDATE()) <= 7
            ) AS hoursThisWeek,
            75 AS overallProgress,
            2 AS achievements
        FROM Student s
        WHERE s.parent_id = :parent_id
    """), {"parent_id": parent_id})

    result["children"] = [dict(row._mapping) for row in children_data]

    print("[GetParentDashboard] Children data:", result["children"])

    # Upcoming Sessions
    upcoming_sessions = db.session.execute(text("""
        SELECT 
            v.SessionID AS id,
            FORMAT(v.CallStartTime, 'dddd') AS day,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            s.name AS childName,
            t.name AS teacher,
            'Quran Session' AS topic,
            'scheduled' AS status
        FROM VideoCallSession v
        JOIN Student s ON v.StudentID = s.id
        JOIN Teacher t ON v.TeacherID = t.id
        WHERE s.parent_id = :parent_id AND v.CallStartTime > GETDATE()
        ORDER BY v.CallStartTime
    """), {"parent_id": parent_id})

    result["upcomingSessions"] = [dict(row) for row in upcoming_sessions]

    return jsonify(result)



@app.route("/GetTeacherProfile", methods=["GET"])
def GetTeacherProfile():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Main teacher info
    teacher_query = """
    SELECT * FROM Teacher WHERE username = :username
    """
    teacher = db.session.execute(text(teacher_query), {"username": username}).fetchone()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    teacher_data = dict(teacher._mapping)

    teacher_data["role"] = "Teacher"

    # Languages
    lang_query = "SELECT Languages FROM Teacher_Languages WHERE TeacherID = :id"
    languages = db.session.execute(text(lang_query), {"id": teacher_data["id"]}).fetchall()
    teacher_data["languages"] = [lang[0] for lang in languages]

    # Courses
    course_query = """
    SELECT c.id, c.name, c.description, c.Sub_title 
    FROM TeacherCourse tc 
    JOIN Course c ON tc.course_id = c.id 
    WHERE tc.qari_id = :id
    """
    courses = db.session.execute(text(course_query), {"id": teacher_data["id"]}).fetchall()
    teacher_data["courses"] = [dict(row._mapping) for row in courses]

    # Schedule
    schedule_query = "SELECT id, day FROM TeacherSchedule WHERE teacher_id = :id"
    schedule = db.session.execute(text(schedule_query), {"id": teacher_data["id"]}).fetchall()
    teacher_data["schedule"] = [dict(row._mapping) for row in schedule]

    return jsonify(teacher_data), 200


@app.route('/GetTeacherDashboard', methods=['GET'])
def GetTeacherDashboard():
    username = request.args.get('username')

    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get teacher ID
    teacher_id_query = db.session.execute(text("""
        SELECT id FROM Teacher WHERE username = :username
    """), {"username": username})
    teacher_row = teacher_id_query.fetchone()

    if not teacher_row:
        return jsonify({"error": "Teacher not found"}), 404

    teacher_id = teacher_row.id

    # Prepare dashboard metrics
    results = {}

    # Total students
    student_count = db.session.execute(text("""
        SELECT COUNT(DISTINCT student_id) AS total_students
        FROM Enrollment
        WHERE qari_id = :teacher_id
    """), {"teacher_id": teacher_id}).scalar()
    results["totalStudents"] = student_count or 0

    # New students this month
    new_students = db.session.execute(text("""
        SELECT COUNT(*) FROM Enrollment
        WHERE qari_id = :teacher_id AND MONTH(start_date) = MONTH(GETDATE()) AND YEAR(start_date) = YEAR(GETDATE())
    """), {"teacher_id": teacher_id}).scalar()
    results["newStudentsThisMonth"] = new_students or 0

    # Active courses
    active_courses = db.session.execute(text("""
        SELECT COUNT(DISTINCT course_id)
        FROM TeacherCourse
        WHERE qari_id = :teacher_id
    """), {"teacher_id": teacher_id}).scalar()
    results["activeCourses"] = active_courses or 0

    # Course completion rate
    total_enrollments = db.session.execute(text("""
        SELECT COUNT(*) FROM Enrollment WHERE qari_id = :teacher_id
    """), {"teacher_id": teacher_id}).scalar()

    completed_enrollments = db.session.execute(text("""
        SELECT COUNT(*) FROM Enrollment WHERE qari_id = :teacher_id AND completed = 1
    """), {"teacher_id": teacher_id}).scalar()

    if total_enrollments:
        results["courseCompletionRate"] = round((completed_enrollments / total_enrollments) * 100, 2)
    else:
        results["courseCompletionRate"] = 0

    # Hours this month
    hours_this_month = db.session.execute(text("""
        SELECT COALESCE(SUM(DATEDIFF(MINUTE, CallStartTime, CallEndTime)), 0) / 60.0
        FROM VideoCallSession
        WHERE TeacherID = :teacher_id AND MONTH(CallStartTime) = MONTH(GETDATE()) AND YEAR(CallStartTime) = YEAR(GETDATE())
    """), {"teacher_id": teacher_id}).scalar()
    results["hoursThisMonth"] = round(hours_this_month or 0, 1)

    # Session completion
    session_stats = db.session.execute(text("""
        SELECT 
            COUNT(*) AS total_sessions,
            COUNT(CASE WHEN CallEndTime IS NOT NULL THEN 1 END) AS completed_sessions
        FROM VideoCallSession
        WHERE TeacherID = :teacher_id
    """), {"teacher_id": teacher_id}).fetchone()
    results["totalSessions"] = session_stats.total_sessions
    results["completedSessions"] = session_stats.completed_sessions
    results["sessionCompletionRate"] = round((session_stats.completed_sessions / session_stats.total_sessions) * 100, 2) if session_stats.total_sessions else 0

    # Rating
    rating_stats = db.session.execute(text("""
        SELECT AVG(CAST(RatingValue AS FLOAT)) AS avg_rating, COUNT(*) AS total_reviews
        FROM TeacherRating
        WHERE TeacherID = :teacher_id
    """), {"teacher_id": teacher_id}).fetchone()
    results["averageRating"] = round(rating_stats.avg_rating or 0, 1)
    results["totalReviews"] = rating_stats.total_reviews

    # Today's schedule
    todays_schedule_query = db.session.execute(text("""
        SELECT 
            v.SessionID AS id,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            s.name AS studentName,
            c.name AS course,
            'Quran Session' AS topic
        FROM VideoCallSession v
        JOIN Student s ON s.id = v.StudentID
        JOIN Enrollment e ON e.student_id = s.id AND e.qari_id = v.TeacherID
        JOIN Course c ON c.id = e.course_id
        WHERE v.TeacherID = :teacher_id 
            AND CAST(v.CallStartTime AS DATE) = CAST(GETDATE() AS DATE)
        ORDER BY v.CallStartTime
    """), {"teacher_id": teacher_id})
    results["todaysSchedule"] = [dict(row._mapping) for row in todays_schedule_query.fetchall()]

    # Recent students
    recent_students_query = text("""
        SELECT DISTINCT TOP 5
            s.id,
            s.name,
            s.pic AS avatar,
            c.name AS currentCourse,
            COALESCE(AVG(CAST(r.RatingValue AS FLOAT)), 0) AS rating,
            75 AS progress  -- You can update this with dynamic logic
        FROM Enrollment e
        JOIN Student s ON s.id = e.student_id
        JOIN Course c ON c.id = e.course_id
        LEFT JOIN TeacherRating r ON r.StudentID = s.id AND r.TeacherID = :teacher_id
        WHERE e.qari_id = :teacher_id
        GROUP BY s.id, s.name, s.pic, c.name
        ORDER BY s.id DESC
    """)
    recent_students = db.session.execute(recent_students_query, {"teacher_id": teacher_id})
    results["recentStudents"] = [dict(row._mapping) for row in recent_students.fetchall()]

    return jsonify(results)


@app.route("/GetStudentProfile", methods=["GET"])
def GetStudentProfile():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Main student info
    student_query = "SELECT * FROM Student WHERE username = :username"
    student = db.session.execute(text(student_query), {"username": username}).fetchone()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_data = dict(student._mapping)

    # Enrollment info with teacher and course
    enroll_query = """
    SELECT 
        e.id AS enrollment_id,
        c.name AS course_name, c.description, c.Sub_title,
        t.name AS teacher_name, t.username AS teacher_username, 'Student' AS role, t.region AS teacher_region
    FROM Enrollment e
    JOIN Course c ON e.course_id = c.id
    JOIN Teacher t ON e.qari_id = t.id
    WHERE e.student_id = :id
    """
    enrollments = db.session.execute(text(enroll_query), {"id": student_data["id"]}).fetchall()
    student_data["enrollments"] = [dict(row._mapping) for row in enrollments]

    return jsonify(student_data), 200


@app.route("/GetStudentDashboard", methods=["GET"])
def GetStudentDashboard():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get student ID
    student_query = "SELECT id FROM Student WHERE username = :username"
    student = db.session.execute(text(student_query), {"username": username}).fetchone()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_id = student.id

    # Count Enrollments
    courses_query = """
        SELECT e.id AS enrollment_id, c.id AS course_id, c.name AS course_title, 
    t.name AS teacher_name, t.id AS teacher_id, e.student_id
    FROM Enrollment e
    JOIN Course c ON e.course_id = c.id
    JOIN Teacher t ON e.qari_id = t.id
    WHERE e.student_id = :student_id
    """
    enrollments = db.session.execute(text(courses_query), {"student_id": student_id}).fetchall()

    enrolled_courses = []
    total_lessons_completed = 0
    total_lessons_available = 0

    for enroll in enrollments:
        # Lessons for this course (per student)
        lesson_query = """
        SELECT COUNT(*) AS total_lessons,
               SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS completed_lessons
        FROM StudentLessonProgress WHERE student_id = :student_id AND course_id = :course_id
        """
        lesson_data = db.session.execute(text(lesson_query), {"student_id": student_id, "course_id": enroll.course_id}).fetchone()
        total = lesson_data.total_lessons or 0
        completed = lesson_data.completed_lessons or 0

        progress = int((completed / total) * 100) if total > 0 else 0
        total_lessons_completed += completed
        total_lessons_available += total

        enrolled_courses.append({
            "id": enroll.course_id,
            "title": enroll.course_title,
            "teacher": enroll.teacher_name,
            "progress": progress,
            "completed": completed,
            "lessons": total
        })

    # Progress Summary
    overall_progress = int((total_lessons_completed / total_lessons_available) * 100) if total_lessons_available > 0 else 0

    # Upcoming Slots
    upcoming_query = """
    SELECT 
        v.Sessionid AS id,
        t.name AS teacher,
        s.time AS time,
        sch.day AS day,
        DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
        c.name AS topic
    FROM VideoCallSession v
    JOIN Slot s ON v.SlotID = s.slot_id
    JOIN TeacherSchedule sch ON s.sch_id = sch.id
    JOIN Teacher t ON v.TeacherID = t.id
    JOIN Enrollment e ON e.qari_id = t.id AND e.student_id = v.StudentID
    JOIN Course c ON e.course_id = c.id
    WHERE v.StudentID = :student_id AND v.CallStartTime >= GETDATE()
    ORDER BY v.CallStartTime ASC
    """
    slots = db.session.execute(text(upcoming_query), {"student_id": student_id}).fetchall()
    upcoming_slots = []
    for slot in slots:
        upcoming_slots.append({
            "id": slot.id,
            "teacher": slot.teacher,
            "time": slot.time,
            "day": slot.day,
            "duration": f"{slot.duration} min" if slot.duration else "N/A",
            "topic": slot.topic
        })

    # Dashboard Stats
    dashboard_data = {
        "overallProgress": overall_progress,
        "coursesInProgress": len(enrolled_courses),
        "totalHours": len(slots),  # 1 session = 1 hour approx
        "lessonsCompleted": total_lessons_completed,
        "upcomingSlots": upcoming_slots,
        "enrolledCourses": enrolled_courses
    }

    return jsonify(dashboard_data), 200


def get_profile_query(role):
    if role == "teacher":
        return text("""
            SELECT id, name, username, 'Teacher' AS role, pic AS avatar
            FROM Teacher
            WHERE username = :username
        """)
    elif role == "parent":
        return text("""
            SELECT id, name, username, 'Parent' AS role, pic AS avatar
            FROM Parent
            WHERE username = :username
        """)
    elif role == "student":
        return text("""
            SELECT id, name, username, 'Student' AS role, pic AS avatar
            FROM Student
            WHERE username = :username
        """)
    else:
        return None


@app.route("/Get<role>Profile", methods=["GET"])
def get_user_profile(role):
    username = request.args.get("username")
    
    if not username:
        return jsonify({"error": "Username is required"}), 400

    role = role.lower()
    query = get_profile_query(role)

    if query is None:
        return jsonify({"error": "Invalid role"}), 400

    result = db.session.execute(query, {"username": username}).fetchone()
    
    if not result:
        return jsonify({"error": f"{role.capitalize()} not found"}), 404

    return jsonify(dict(result))


def fetch_children_for_parent(username):
    parent = db.session.execute(
        text("SELECT id FROM Parent WHERE username = :username"),
        {"username": username}
    ).fetchone()
    if not parent:
        return None, "Parent not found"
    parent_id = parent.id
    # Join Student and Enrollment to get enrolledDate for each child (earliest enrollment)
    children = db.session.execute(text("""
        SELECT 
            s.id,
            s.name,                                       
            s.username,
            s.pic AS avatar,
            s.dob,
            MIN(e.start_date) AS enrolledDate  -- earliest enrollment date
        FROM Student s
        LEFT JOIN Enrollment e ON e.student_id = s.id
        WHERE s.parent_id = :parent_id
        GROUP BY s.id, s.name, s.username, s.pic, s.dob
    """), {"parent_id": parent_id}).fetchall()
    return children, None

@app.route("/api/parent/children-progress", methods=["GET"])
def get_children_progress():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    children, error = fetch_children_for_parent(username)
    if error:
        return jsonify({"error": error}), 404

    children_list = []
    for child in children:
        dob = child.dob
        age = None
        if dob:
            today = datetime.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        total_lessons_query = text("""
            SELECT COUNT(*) AS total_lessons
            FROM QuranLessons ql
            JOIN Enrollment e ON ql.CourseID = e.course_id
            WHERE e.student_id = :student_id
        """)
        total_lessons_result = db.session.execute(total_lessons_query, {"student_id": child.id}).fetchone()
        total_lessons = total_lessons_result.total_lessons or 0
        
        completed_lessons_query = text("""
            SELECT COUNT(*) AS completed_lessons
            FROM StudentLessonProgress 
            WHERE student_id = :student_id AND status = 1
        """)
        completed_lessons_result = db.session.execute(completed_lessons_query, {"student_id": child.id}).fetchone()
        completed_lessons = completed_lessons_result.completed_lessons or 0
        
        overall_progress = int((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0

        # Get total hours from video call sessions
        total_hours = db.session.execute(
            text("SELECT COALESCE(SUM(DATEDIFF(MINUTE, CallStartTime, CallEndTime)), 0) / 60.0 FROM VideoCallSession WHERE StudentID = :student_id"),
            {"student_id": child.id}
        ).scalar()

        # Get enrolled courses for this child, including teacher name
        courses = db.session.execute(text("""
            SELECT c.id, c.name, c.description, t.username AS t_username
            FROM Enrollment e
            JOIN Course c ON e.course_id = c.id
            JOIN Teacher t ON e.qari_id = t.id
            WHERE e.student_id = :student_id
        """), {"student_id": child.id}).fetchall()
        courses_list = []
        for course in courses:
            # Get total lessons for this course
            total_course_lessons = db.session.execute(
                text("SELECT COUNT(*) FROM QuranLessons WHERE CourseID = :course_id"),
                {"course_id": course.id}
            ).scalar() or 0
            courses_list.append({
                "id": course.id,
                "name": course.name,
                "description": course.description,
                "teacher_username": course.t_username,
                "totalLessons": total_course_lessons
            })

        children_list.append({
            "id": child.id,
            "username": child.username,
            "name": child.name,
            "avatar": child.avatar or "",  
            "age": age,
            "enrolledDate": child.enrolledDate if hasattr(child, 'enrolledDate') else None,
            "overallProgress": overall_progress,
            "totalHours": round(total_hours or 0, 1),
            "totalLessons": total_lessons,
            "completedLessons": completed_lessons,
            "courses": courses_list
        })

    return jsonify({"children": children_list})


@app.route("/api/profile", methods=["GET"])
def get_profile():
    username = request.args.get("username")
    role = request.args.get("role", "").lower()

    if not username or not role:
        return jsonify({"error": "Username and role are required"}), 400

    # Default values for all fields
    profile = {
        "firstName": "",
        "lastName": "",
        "email": "",
        "phone": "",
        "dateOfBirth": "",
        "location": "",
        "bio": "",
        "avatar": "/placeholder.svg",
        "joinDate": "",
        "role": role.capitalize(),
    }

    if role == "student":
        query = text("""
            SELECT
                name,
                username,
                dob,
                region,
                pic
            FROM Student
            WHERE username = :username
        """)
        result = db.session.execute(query, {"username": username}).fetchone()
        if not result:
            return jsonify({"error": "User not found"}), 404
        # Split name
        name_parts = (result.name or "").split(" ", 1)
        profile["firstName"] = name_parts[0] if name_parts else ""
        profile["lastName"] = name_parts[1] if len(name_parts) > 1 else ""
        profile["dateOfBirth"] = str(result.dob) if result.dob else ""
        profile["location"] = result.region or ""
        profile["avatar"] = result.pic or "/placeholder.svg"
        # joinDate fallback to dob or empty
        profile["joinDate"] = str(result.dob) if result.dob else ""
    elif role == "teacher":
        query = text("""
            SELECT
                name,
                username,
                dob,
                region,
                pic,
                bio
            FROM Teacher
            WHERE username = :username
        """)
        result = db.session.execute(query, {"username": username}).fetchone()
        if not result:
            return jsonify({"error": "User not found"}), 404
        name_parts = (result.name or "").split(" ", 1)
        profile["firstName"] = name_parts[0] if name_parts else ""
        profile["lastName"] = name_parts[1] if len(name_parts) > 1 else ""
        profile["dateOfBirth"] = str(result.dob) if result.dob else ""
        profile["location"] = result.region or ""
        profile["avatar"] = result.pic or "/placeholder.svg"
        profile["bio"] = result.bio or ""
        profile["joinDate"] = str(result.dob) if result.dob else ""
    elif role == "parent":
        query = text("""
            SELECT
                name,
                username,
                region
            FROM Parent
            WHERE username = :username
        """)
        result = db.session.execute(query, {"username": username}).fetchone()
        if not result:
            return jsonify({"error": "User not found"}), 404
        name_parts = (result.name or "").split(" ", 1)
        profile["firstName"] = name_parts[0] if name_parts else ""
        profile["lastName"] = name_parts[1] if len(name_parts) > 1 else ""
        profile["location"] = result.region or ""
    else:
        return jsonify({"error": "Invalid role"}), 400

    return jsonify(profile)


@app.route("/GetStudentSettings", methods=["GET"])
def GetStudentSettings():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get student settings/info
    query = text("""
        SELECT 
            id,
            username,
            name,
            password,
            region,
            gender,
            dob,
            pic,
            parent_id
        FROM Student
        WHERE username = :username
    """)
    
    result = db.session.execute(query, {"username": username}).fetchone()
    if not result:
        return jsonify({"error": "Student not found"}), 404

    # Split name into first and last name
    full_name = result.name or ""
    name_parts = full_name.split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    settings = {
        "id": result.id,
        "username": result.username,
        "firstName": first_name,
        "lastName": last_name,
        "password": result.password,
        "region": result.region,
        "gender": result.gender,
        "dateOfBirth": str(result.dob) if result.dob else "",
        "avatar": result.pic or "/placeholder.svg",
        "parentId": result.parent_id,
        "role": "Student"
    }

    return jsonify(settings), 200


@app.route("/UpdateStudentSettings", methods=["POST"])
def UpdateStudentSettings():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Extract fields from request
    first_name = data.get("firstName", "")
    last_name = data.get("lastName", "")
    password = data.get("password", "")
    region = data.get("region", "")
    gender = data.get("gender", "")
    date_of_birth = data.get("dateOfBirth", "")
    avatar = data.get("avatar", "")

    # Combine first and last name
    full_name = f"{first_name} {last_name}".strip()

    try:
        # Build update query dynamically based on provided fields
        update_fields = []
        params = {"username": username}

        if first_name or last_name:
            update_fields.append("name = :name")
            params["name"] = full_name

        if password:
            update_fields.append("password = :password")
            params["password"] = password

        if region:
            update_fields.append("region = :region")
            params["region"] = region

        if gender:
            update_fields.append("gender = :gender")
            params["gender"] = gender

        if date_of_birth:
            update_fields.append("dob = :dob")
            params["dob"] = date_of_birth

        if avatar:
            update_fields.append("pic = :pic")
            params["pic"] = avatar

        if not update_fields:
            return jsonify({"error": "No valid fields to update"}), 400

        # Execute update
        update_query = text(f"""
            UPDATE Student 
            SET {', '.join(update_fields)}
            WHERE username = :username
        """)

        result = db.session.execute(update_query, params)
        db.session.commit()

        if result.rowcount == 0:
            return jsonify({"error": "Student not found"}), 404

        return jsonify({"message": "Student settings updated successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to update student settings", "details": str(e)}), 500


@app.route("/GetTeacherSettings", methods=["GET"])
def GetTeacherSettings():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get teacher settings/info
    query = text("""
        SELECT 
            id,
            username,
            name,
            password,
            region,
            gender,
            dob,
            pic,
            qualification,
            cnic,
            bio,
            hourly_rate
        FROM Teacher
        WHERE username = :username
    """)
    
    result = db.session.execute(query, {"username": username}).fetchone()
    if not result:
        return jsonify({"error": "Teacher not found"}), 404

    # Split name into first and last name
    full_name = result.name or ""
    name_parts = full_name.split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    settings = {
        "id": result.id,
        "username": result.username,
        "firstName": first_name,
        "lastName": last_name,
        "password": result.password,
        "region": result.region,
        "gender": result.gender,
        "dateOfBirth": str(result.dob) if result.dob else "",
        "avatar": result.pic or "/placeholder.svg",
        "qualification": result.qualification,
        "cnic": result.cnic,
        "bio": result.bio,
        "hourlyRate": result.hourly_rate,
        "role": "Teacher"
    }

    return jsonify(settings), 200


@app.route("/UpdateTeacherSettings", methods=["POST"])
def UpdateTeacherSettings():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Extract fields from request
    first_name = data.get("firstName", "")
    last_name = data.get("lastName", "")
    password = data.get("password", "")
    region = data.get("region", "")
    gender = data.get("gender", "")
    date_of_birth = data.get("dateOfBirth", "")
    avatar = data.get("avatar", "")
    qualification = data.get("qualification", "")
    bio = data.get("bio", "")
    hourly_rate = data.get("hourlyRate", "")

    # Combine first and last name
    full_name = f"{first_name} {last_name}".strip()

    try:
        # Build update query dynamically based on provided fields
        update_fields = []
        params = {"username": username}

        if first_name or last_name:
            update_fields.append("name = :name")
            params["name"] = full_name

        if password:
            update_fields.append("password = :password")
            params["password"] = password

        if region:
            update_fields.append("region = :region")
            params["region"] = region

        if gender:
            update_fields.append("gender = :gender")
            params["gender"] = gender

        if date_of_birth:
            update_fields.append("dob = :dob")
            params["dob"] = date_of_birth

        if avatar:
            update_fields.append("pic = :pic")
            params["pic"] = avatar

        if qualification:
            update_fields.append("qualification = :qualification")
            params["qualification"] = qualification

        if bio:
            update_fields.append("bio = :bio")
            params["bio"] = bio

        if hourly_rate:
            update_fields.append("hourly_rate = :hourly_rate")
            params["hourly_rate"] = hourly_rate

        if not update_fields:
            return jsonify({"error": "No valid fields to update"}), 400

        # Execute update
        update_query = text(f"""
            UPDATE Teacher 
            SET {', '.join(update_fields)}
            WHERE username = :username
        """)

        result = db.session.execute(update_query, params)
        db.session.commit()

        if result.rowcount == 0:
            return jsonify({"error": "Teacher not found"}), 404

        return jsonify({"message": "Teacher settings updated successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to update teacher settings", "details": str(e)}), 500


@app.route("/GetParentSettings", methods=["GET"])
def GetParentSettings():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get parent settings/info
    query = text("""
        SELECT 
            id,
            username,
            name,
            password,
            region,
            cnic,
            pic
        FROM Parent
        WHERE username = :username
    """)
    
    result = db.session.execute(query, {"username": username}).fetchone()
    if not result:
        return jsonify({"error": "Parent not found"}), 404

    # Split name into first and last name
    full_name = result.name or ""
    name_parts = full_name.split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    settings = {
        "id": result.id,
        "username": result.username,
        "firstName": first_name,
        "lastName": last_name,
        "password": result.password,
        "region": result.region,
        "cnic": result.cnic,
        "avatar": result.pic or "/placeholder.svg",
        "role": "Parent"
    }

    return jsonify(settings), 200


@app.route("/UpdateParentSettings", methods=["POST"])
def UpdateParentSettings():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Extract fields from request
    first_name = data.get("firstName", "")
    last_name = data.get("lastName", "")
    password = data.get("password", "")
    region = data.get("region", "")
    cnic = data.get("cnic", "")
    avatar = data.get("avatar", "")

    # Combine first and last name
    full_name = f"{first_name} {last_name}".strip()

    try:
        # Build update query dynamically based on provided fields
        update_fields = []
        params = {"username": username}

        if first_name or last_name:
            update_fields.append("name = :name")
            params["name"] = full_name

        if password:
            update_fields.append("password = :password")
            params["password"] = password

        if region:
            update_fields.append("region = :region")
            params["region"] = region

        if cnic:
            update_fields.append("cnic = :cnic")
            params["cnic"] = cnic

        if avatar:
            update_fields.append("pic = :pic")
            params["pic"] = avatar

        if not update_fields:
            return jsonify({"error": "No valid fields to update"}), 400

        # Execute update
        update_query = text(f"""
            UPDATE Parent 
            SET {', '.join(update_fields)}
            WHERE username = :username
        """)

        result = db.session.execute(update_query, params)
        db.session.commit()

        if result.rowcount == 0:
            return jsonify({"error": "Parent not found"}), 404

        return jsonify({"message": "Parent settings updated successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to update parent settings", "details": str(e)}), 500


@app.route("/GetTeachersByCourse", methods=["GET"])
def GetTeachersByCourse():
    id = request.args.get("id")

    try:
        query = text(
            f"Select qari_id,name,gender,region,pic from TeacherCourse tc inner JOIN Teacher t ON t.id = tc.qari_id where tc.course_id='{id}'"
        )
        result = db.session.execute(query)
        rw = []
        keys = [
            "qari_id",
            "name",
            "gender",
            "region",
            "pic",
        ]
        for row in result:
            rw.append(dict(zip(keys, row)))

        return jsonify(rw)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/getAvailableSlots", methods=["GET"])
def avail_slots():
    qari_id = request.args.get("qari_id")
    query = text(
        f"""SELECT t.id AS qariId, t.name AS qariName, ts.day, s.time, s.slot_id, c.id as course_id, c.name as course_name FROM Teacher t 
                    INNER JOIN TeacherSchedule ts ON t.id = ts.teacher_id 
                    INNER JOIN Slot s ON ts.id = s.sch_id
                    LEFT JOIN Course c ON s.Course_id = c.id
                    WHERE t.id = '{qari_id}' AND s.booked = 0"""
    )
    try:
        res = db.session.execute(query)
        rw = []
        keys = [
            "qariId",
            "qariName",
            "day",
            "time",
            "slot_id",
            "course_id",
            "course_name"
        ]
        for row in res:
            rw.append(dict(zip(keys, row)))
        return jsonify(rw)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bookSlots", methods=["POST"])
def book_slots():
    body = request.json
    qari_id = body.get("qari_id")
    student_id = body.get("student_id")
    course_id = body.get("course_id")
    slots = body.get("slots")  # [ 1, 2, 3, 4, 5] => 1,2,3,4,5
    try:
        bookedSlots = ",".join([str(x) for x in slots])
        res = db.session.execute(
            text(
                f"INSERT INTO Enrollment (student_id, qari_id, course_id) OUTPUT inserted.id VALUES('{student_id}', '{qari_id}', '{course_id}')"
            )
        )
        generated_id = res.scalar()
        bookQuery = text(f"UPDATE Slot SET booked = 1, Course_id = {course_id} WHERE slot_id IN({bookedSlots})")
        db.session.execute(bookQuery)
        for i in slots:
            db.session.execute(
                text(
                    f"INSERT INTO BookedEnrollmentSlots VALUES('{generated_id}', '{i}')"
                )
            )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/GetEnrolledCourses", methods=["Get"])
def EnrolledCourses():
    stu_id = request.args.get("stu_id")
    query = text(
        f"""SELECT s.name as Studentname, c.name as Coursename, c.description as coursedescription, t.name AS TeacherName, sl.time as SlotTime FROM Student s 
                    INNER JOIN Enrollment e
                    ON s.id = e.student_id
                    INNER JOIN Course c
                    ON e.course_id = c.id
                    INNER JOIN Teacher t
                    ON t.id = e.qari_id
                    INNER JOIN BookedEnrollmentSlots bs 
                    ON bs.enrollment_id = e.id
                    INNER JOIN Slot sl 
                    ON sl.slot_id = bs.slot_id 
                    where s.id='{stu_id}'"""
    )
    print(query)
    try:
        res = db.session.execute(query)
        rw = []
        keys = [
            "Studentname",
            "CourseName",
            "coursedescription",
            "Teachername",
            "SlotTime",
        ]
        for row in res:
            rw.append(dict(zip(keys, row)))
        return jsonify(rw)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/GetCourses", methods=["Get"])
def get_course():
    rows = db.session.execute(text("Select * from Course"))
    rw = []
    keys = ["c_id", "c_name", "c_desc"]
    for row in rows:
        rw.append(dict(zip(keys, row)))

    return jsonify(rw)


# Teacher Side
@app.route("/UpdateTeacherByUsername", methods=["POST"])
def UpdateTeacherByUsername():
    # Get the username from query parameters
    username = request.args.get("username")

    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get the body of the request
    body = request.json
    print(body)

    # Extract values from the body
    name = body.get("name", "def")
    password = body.get("password", "def")
    pic = body.get("pic", "def")
    dob = body.get("dob", "def")
    qualification = body.get("qualification", "def")
    region = body.get("region", "def")

    try:
        query = text(
            f"""
            UPDATE Teacher
            SET name = '{name}',
                password = '{password}',
                pic = '{pic}',
                dob = '{dob}',
                qualification = '{qualification}',
                region = '{region}'
            WHERE username = '{username}'
        """
        )

        db.session.execute(query)
        db.session.commit()

        return (
            jsonify(
                {"message": f"Teacher with username '{username}' updated successfully"}
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/GetQariCoursesAndSchedule", methods=["GET"])
def GetQariCoursesAndSchedule():
    qari_id = request.args.get("qari_id")
    if not qari_id:
        return jsonify({"error": "Qari ID is required"}), 400
    query = text(
        """
            SELECT t.id AS QariId, t.name AS QariName, ts.day AS ScheduleDay, s.time AS SlotTime, s.slot_id AS SlotId, s.booked AS IsBooked, c.id AS CourseId, c.name AS CourseName, c.description AS CourseDescription
            FROM Teacher t
            INNER JOIN TeacherSchedule ts ON t.id = ts.teacher_id
            INNER JOIN Slot s ON ts.id = s.sch_id
            LEFT JOIN Course c ON s.Course_id = c.id
            WHERE t.id = :qari_id
        """
    )
    try:
        result = db.session.execute(query, {"qari_id": qari_id})
        rw = []
        keys = [
            "QariId",
            "QariName",
            "ScheduleDay",
            "SlotTime",
            "SlotId",
            "IsBooked",
            "CourseId",
            "CourseName",
            "CourseDescription"
        ]
        for row in result:
            rw.append(dict(zip(keys, row)))
        if not rw:
            return (
                jsonify(
                    {"message": "No courses or schedules found for the specified Qari"}
                ),
                404,
            )
        return jsonify(rw), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/GetStudentSchedule", methods=["GET"])
def GetStudentSchedule():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get student ID
    student_query = "SELECT id FROM Student WHERE username = :username"
    student = db.session.execute(text(student_query), {"username": username}).fetchone()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_id = student.id

    # Get upcoming sessions
    upcoming_sessions_query = text("""
        SELECT 
            v.SessionID AS id,
            v.CallStartTime AS startTime,
            v.CallEndTime AS endTime,
            FORMAT(v.CallStartTime, 'dddd') AS day,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            t.name AS teacherName,
            t.username AS teacherUsername,
            t.pic AS teacherAvatar,
            c.name AS courseName,
            c.description AS courseDescription,
            'scheduled' AS status
        FROM VideoCallSession v
        JOIN Teacher t ON v.TeacherID = t.id
        JOIN Enrollment e ON e.qari_id = t.id AND e.student_id = v.StudentID
        JOIN Course c ON e.course_id = c.id
        WHERE v.StudentID = :student_id 
            AND v.CallStartTime >= GETDATE()
        ORDER BY v.CallStartTime ASC
    """)

    upcoming_sessions = db.session.execute(upcoming_sessions_query, {"student_id": student_id}).fetchall()

    # Get completed sessions (last 5)
    completed_sessions_query = text("""
        SELECT 
            v.SessionID AS id,
            v.CallStartTime AS startTime,
            v.CallEndTime AS endTime,
            FORMAT(v.CallStartTime, 'dddd, MMM dd') AS date,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            t.name AS teacherName,
            t.username AS teacherUsername,
            t.pic AS teacherAvatar,
            c.name AS courseName,
            'completed' AS status
        FROM VideoCallSession v
        JOIN Teacher t ON v.TeacherID = t.id
        JOIN Enrollment e ON e.qari_id = t.id AND e.student_id = v.StudentID
        JOIN Course c ON e.course_id = c.id
        WHERE v.StudentID = :student_id 
            AND v.CallEndTime IS NOT NULL
        ORDER BY v.CallStartTime DESC
        OFFSET 0 ROWS FETCH NEXT 5 ROWS ONLY
    """)

    completed_sessions = db.session.execute(completed_sessions_query, {"student_id": student_id}).fetchall()

    # Get today's sessions
    today_sessions_query = text("""
        SELECT 
            v.SessionID AS id,
            v.CallStartTime AS startTime,
            v.CallEndTime AS endTime,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            t.name AS teacherName,
            t.username AS teacherUsername,
            t.pic AS teacherAvatar,
            c.name AS courseName,
            CASE 
                WHEN v.CallStartTime <= GETDATE() AND v.CallEndTime >= GETDATE() THEN 'ongoing'
                WHEN v.CallStartTime > GETDATE() THEN 'upcoming'
                ELSE 'completed'
            END AS status
        FROM VideoCallSession v
        JOIN Teacher t ON v.TeacherID = t.id
        JOIN Enrollment e ON e.qari_id = t.id AND e.student_id = v.StudentID
        JOIN Course c ON e.course_id = c.id
        WHERE v.StudentID = :student_id 
            AND CAST(v.CallStartTime AS DATE) = CAST(GETDATE() AS DATE)
        ORDER BY v.CallStartTime ASC
    """)

    today_sessions = db.session.execute(today_sessions_query, {"student_id": student_id}).fetchall()

    # Get weekly schedule summary
    weekly_summary_query = text("""
        SELECT 
            FORMAT(v.CallStartTime, 'dddd') AS day,
            COUNT(*) AS sessionCount,
            SUM(DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime)) AS totalMinutes
        FROM VideoCallSession v
        WHERE v.StudentID = :student_id 
            AND v.CallStartTime >= DATEADD(day, -7, GETDATE())
            AND v.CallStartTime < DATEADD(day, 7, GETDATE())
        GROUP BY FORMAT(v.CallStartTime, 'dddd')
        ORDER BY 
            CASE FORMAT(v.CallStartTime, 'dddd')
                WHEN 'Sunday' THEN 1
                WHEN 'Monday' THEN 2
                WHEN 'Tuesday' THEN 3
                WHEN 'Wednesday' THEN 4
                WHEN 'Thursday' THEN 5
                WHEN 'Friday' THEN 6
                WHEN 'Saturday' THEN 7
            END
    """)

    weekly_summary = db.session.execute(weekly_summary_query, {"student_id": student_id}).fetchall()

    # Convert to dictionaries
    schedule_data = {
        "upcomingSessions": [dict(row._mapping) for row in upcoming_sessions],
        "completedSessions": [dict(row._mapping) for row in completed_sessions],
        "todaySessions": [dict(row._mapping) for row in today_sessions],
        "weeklySummary": [dict(row._mapping) for row in weekly_summary],
        "totalUpcoming": len(upcoming_sessions),
        "totalCompleted": len(completed_sessions),
        "totalToday": len(today_sessions)
    }

    return jsonify(schedule_data), 200


@app.route("/GetTeacherSchedule", methods=["GET"])
def GetTeacherSchedule():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get teacher ID
    teacher_query = "SELECT id FROM Teacher WHERE username = :username"
    teacher = db.session.execute(text(teacher_query), {"username": username}).fetchone()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404

    teacher_id = teacher.id

    # Get upcoming sessions
    upcoming_sessions_query = text("""
        SELECT 
            v.SessionID AS id,
            v.CallStartTime AS startTime,
            v.CallEndTime AS endTime,
            FORMAT(v.CallStartTime, 'dddd') AS day,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            s.name AS studentName,
            s.username AS studentUsername,
            s.pic AS studentAvatar,
            c.name AS courseName,
            c.description AS courseDescription,
            'scheduled' AS status
        FROM VideoCallSession v
        JOIN Student s ON v.StudentID = s.id
        JOIN Enrollment e ON e.qari_id = v.TeacherID AND e.student_id = s.id
        JOIN Course c ON e.course_id = c.id
        WHERE v.TeacherID = :teacher_id 
            AND v.CallStartTime >= GETDATE()
        ORDER BY v.CallStartTime ASC
    """)

    upcoming_sessions = db.session.execute(upcoming_sessions_query, {"teacher_id": teacher_id}).fetchall()

    # Get completed sessions (last 5)
    completed_sessions_query = text("""
        SELECT 
            v.SessionID AS id,
            v.CallStartTime AS startTime,
            v.CallEndTime AS endTime,
            FORMAT(v.CallStartTime, 'dddd, MMM dd') AS date,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            s.name AS studentName,
            s.username AS studentUsername,
            s.pic AS studentAvatar,
            c.name AS courseName,
            'completed' AS status
        FROM VideoCallSession v
        JOIN Student s ON v.StudentID = s.id
        JOIN Enrollment e ON e.qari_id = v.TeacherID AND e.student_id = s.id
        JOIN Course c ON e.course_id = c.id
        WHERE v.TeacherID = :teacher_id 
            AND v.CallEndTime IS NOT NULL
        ORDER BY v.CallStartTime DESC
        OFFSET 0 ROWS FETCH NEXT 5 ROWS ONLY
    """)

    completed_sessions = db.session.execute(completed_sessions_query, {"teacher_id": teacher_id}).fetchall()

    # Get today's sessions
    today_sessions_query = text("""
        SELECT 
            v.SessionID AS id,
            v.CallStartTime AS startTime,
            v.CallEndTime AS endTime,
            FORMAT(v.CallStartTime, 'hh:mm tt') AS time,
            DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime) AS duration,
            s.name AS studentName,
            s.username AS studentUsername,
            s.pic AS studentAvatar,
            c.name AS courseName,
            CASE 
                WHEN v.CallStartTime <= GETDATE() AND v.CallEndTime >= GETDATE() THEN 'ongoing'
                WHEN v.CallStartTime > GETDATE() THEN 'upcoming'
                ELSE 'completed'
            END AS status
        FROM VideoCallSession v
        JOIN Student s ON v.StudentID = s.id
        JOIN Enrollment e ON e.qari_id = v.TeacherID AND e.student_id = s.id
        JOIN Course c ON e.course_id = c.id
        WHERE v.TeacherID = :teacher_id 
            AND CAST(v.CallStartTime AS DATE) = CAST(GETDATE() AS DATE)
        ORDER BY v.CallStartTime ASC
    """)

    today_sessions = db.session.execute(today_sessions_query, {"teacher_id": teacher_id}).fetchall()

    # Get weekly schedule summary
    weekly_summary_query = text("""
        SELECT 
            FORMAT(v.CallStartTime, 'dddd') AS day,
            COUNT(*) AS sessionCount,
            SUM(DATEDIFF(MINUTE, v.CallStartTime, v.CallEndTime)) AS totalMinutes
        FROM VideoCallSession v
        WHERE v.TeacherID = :teacher_id 
            AND v.CallStartTime >= DATEADD(day, -7, GETDATE())
            AND v.CallStartTime < DATEADD(day, 7, GETDATE())
        GROUP BY FORMAT(v.CallStartTime, 'dddd')
        ORDER BY 
            CASE FORMAT(v.CallStartTime, 'dddd')
                WHEN 'Sunday' THEN 1
                WHEN 'Monday' THEN 2
                WHEN 'Tuesday' THEN 3
                WHEN 'Wednesday' THEN 4
                WHEN 'Thursday' THEN 5
                WHEN 'Friday' THEN 6
                WHEN 'Saturday' THEN 7
            END
    """)

    weekly_summary = db.session.execute(weekly_summary_query, {"teacher_id": teacher_id}).fetchall()

    # Convert to dictionaries
    schedule_data = {
        "upcomingSessions": [dict(row._mapping) for row in upcoming_sessions],
        "completedSessions": [dict(row._mapping) for row in completed_sessions],
        "todaySessions": [dict(row._mapping) for row in today_sessions],
        "weeklySummary": [dict(row._mapping) for row in weekly_summary],
        "totalUpcoming": len(upcoming_sessions),
        "totalCompleted": len(completed_sessions),
        "totalToday": len(today_sessions)
    }

    return jsonify(schedule_data), 200


@app.route("/GetStudentCourses", methods=["GET"])
def GetStudentCourses():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get student ID
    student = db.session.execute(text("SELECT id FROM Student WHERE username = :username"), {"username": username}).fetchone()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    student_id = student.id

    # Get all courses the student is enrolled in
    query = text("""
        SELECT 
            c.id AS course_id,
            c.name AS course_name,
            c.description AS course_description,
            c.Sub_title AS course_subtitle,
            t.id AS teacher_id,
            t.name AS teacher_name,
            t.username AS teacher_username,
            t.pic AS teacher_avatar
        FROM Enrollment e
        JOIN Course c ON e.course_id = c.id
        JOIN Teacher t ON e.qari_id = t.id
        WHERE e.student_id = :student_id
    """)

    results = db.session.execute(query, {"student_id": student_id}).fetchall()
    courses = []
    for row in results:
        courses.append({
            "courseId": row.course_id,
            "courseName": row.course_name,
            "courseDescription": row.course_description,
            "courseSubtitle": row.course_subtitle,
            "teacherId": row.teacher_id,
            "teacherName": row.teacher_name,
            "teacherUsername": row.teacher_username,
            "teacherAvatar": row.teacher_avatar or "/placeholder.svg"
        })

    return jsonify({"courses": courses}), 200


@app.route('/api/students/<username>/hire', methods=['POST'])
def hire_teacher(username):
    # Get student by username
    student = db.session.execute(
        text("SELECT id FROM Student WHERE username = :username"),
        {"username": username}
    ).fetchone()
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    student_id = student.id

    data = request.get_json()
    teacher_id = data.get('teacherId')
    course_id = data.get('courseId')  # Optional, can be null
    selected_schedule = data.get('selectedSchedule', [])

    if not teacher_id:
        return jsonify({'error': 'teacherId is required'}), 400

    # If course_id is provided, check if course exists
    if course_id:
        course = db.session.execute(text("SELECT id FROM Course WHERE id = :id"), {"id": course_id}).fetchone()
        if not course:
            return jsonify({'error': 'Course not found'}), 404
    else:
        # If not provided, try to find a default course for this teacher
        course = db.session.execute(text("SELECT course_id FROM TeacherCourse WHERE qari_id = :teacher_id"), {"teacher_id": teacher_id}).fetchone()
        if not course:
            return jsonify({'error': 'No course found for this teacher'}), 400
        course_id = course.course_id

    # Check if already enrolled
    existing = db.session.execute(text("""
        SELECT id FROM Enrollment WHERE student_id = :student_id AND qari_id = :teacher_id AND course_id = :course_id
    """), {"student_id": student_id, "teacher_id": teacher_id, "course_id": course_id}).fetchone()
    if existing:
        return jsonify({'error': 'Student is already enrolled with this teacher for this course'}), 409

    try:
        # Get current date
        current_date = datetime.now().date()
        
        # Enroll the student with current date
        enrollment_result = db.session.execute(text("""
            INSERT INTO Enrollment (student_id, qari_id, course_id, start_date) OUTPUT inserted.id VALUES (:student_id, :teacher_id, :course_id, :start_date)
        """), {"student_id": student_id, "teacher_id": teacher_id, "course_id": course_id, "start_date": current_date})
        enrollment_id = enrollment_result.scalar()
        
        # If slots are provided, book them (multiple slots per enrollment)
        if selected_schedule and isinstance(selected_schedule, list):
            # Validate all slot IDs
            valid_slots = db.session.execute(
                text(f"SELECT slot_id FROM Slot WHERE slot_id IN ({','.join(str(int(sid)) for sid in selected_schedule)}) AND booked = 0")
            )
            valid_slot_ids = {row.slot_id for row in valid_slots}
            for slot_id in selected_schedule:
                if int(slot_id) not in valid_slot_ids:
                    db.session.rollback()
                    return jsonify({'error': f'Invalid or already booked slot ID: {slot_id}'}), 400
            # Book slots and set Course_id, and insert into BookedEnrollmentSlots
            for slot_id in selected_schedule:
                db.session.execute(
                    text("UPDATE Slot SET booked = 1, Course_id = :course_id WHERE slot_id = :slot_id"),
                    {"course_id": course_id, "slot_id": int(slot_id)}
                )
                db.session.execute(
                    text("INSERT INTO BookedEnrollmentSlots (enrollment_id, slot_id) VALUES (:enrollment_id, :slot_id)"),
                    {"enrollment_id": enrollment_id, "slot_id": int(slot_id)}
                )
        db.session.commit()
        print("Returning success response for hire-teacher")
        try:
            return jsonify({'message': 'Teacher hired and student enrolled successfully!'}), 201
        except Exception as e:
            print("Error in return:", e)
            return jsonify({'error': 'Response error', 'details': str(e)}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to hire teacher', 'details': str(e)}), 500


@app.route('/GetTeacherCompleteData', methods=['GET'])
def GetTeacherCompleteData():
    username = request.args.get('username')
    if not username:
        return jsonify({'error': 'Username is required'}), 400

    # 1. Main teacher info
    teacher_query = """
    SELECT * FROM Teacher WHERE username = :username
    """
    teacher = db.session.execute(text(teacher_query), {'username': username}).fetchone()
    if not teacher:
        return jsonify({'error': 'Teacher not found'}), 404
    teacher_data = dict(teacher._mapping)
    teacher_id = teacher_data['id']
    teacher_data['role'] = 'Teacher'

    # 2. Languages
    lang_query = "SELECT Languages FROM Teacher_Languages WHERE TeacherID = :id"
    languages = db.session.execute(text(lang_query), {'id': teacher_id}).fetchall()
    teacher_data['languages'] = [lang[0] for lang in languages]

    # 3. Courses
    course_query = """
    SELECT c.id, c.name, c.description, c.Sub_title 
    FROM TeacherCourse tc 
    JOIN Course c ON tc.course_id = c.id 
    WHERE tc.qari_id = :id
    """
    courses = db.session.execute(text(course_query), {'id': teacher_id}).fetchall()
    teacher_data['courses'] = [dict(row._mapping) for row in courses]

    # 4. Schedule with slots and booked status
    schedule_query = text("""
        SELECT ts.id AS schedule_id, ts.day, s.slot_id, s.time, s.booked, s.sch_id, s.Course_id, c.name as course_name,
               st.username as student_username, st.name as student_name
        FROM TeacherSchedule ts
        LEFT JOIN Slot s ON ts.id = s.sch_id
        LEFT JOIN Course c ON s.Course_id = c.id
        LEFT JOIN Enrollment e ON e.qari_id = ts.teacher_id AND e.course_id = s.Course_id
        LEFT JOIN Student st ON e.student_id = st.id
        WHERE ts.teacher_id = :id
        ORDER BY ts.day, s.time
    """)
    schedule = db.session.execute(schedule_query, {'id': teacher_id}).fetchall()
    # Group by day, show all slots for each day
    schedule_list = []
    for row in schedule:
        time_val = row.time
        schedule_list.append({
            "scheduleId": row.schedule_id,
            "day": row.day,
            "slotId": row.slot_id,
            "time": time_val,
            "isBooked": bool(row.booked) if row.booked is not None else None,
            "course": {"courseId": row.Course_id, "courseName": row.course_name} if row.Course_id else None
        })
        
        # Add student information if the slot is booked
        if row.booked and row.student_username:
            schedule_list[-1]["student"] = {
                "username": row.student_username,
                "name": row.student_name
            }

    teacher_data['schedule'] = schedule_list

    # 5. Optionally, add recent students
    recent_students_query = text("""
        SELECT DISTINCT TOP 5
            s.id,
            s.name,
            s.pic AS avatar,
            c.name AS currentCourse,
            COALESCE(AVG(CAST(r.RatingValue AS FLOAT)), 0) AS rating,
            75 AS progress  -- You can update this with dynamic logic
        FROM Enrollment e
        JOIN Student s ON s.id = e.student_id
        JOIN Course c ON c.id = e.course_id
        LEFT JOIN TeacherRating r ON r.StudentID = s.id AND r.TeacherID = :teacher_id
        WHERE e.qari_id = :teacher_id
        GROUP BY s.id, s.name, s.pic, c.name
        ORDER BY s.id DESC
    """)
    recent_students = db.session.execute(recent_students_query, {"teacher_id": teacher_id})
    teacher_data['recentStudents'] = [dict(row._mapping) for row in recent_students.fetchall()]

    # 6. Optionally, add dashboard stats
    # (You can add more stats here if needed)

    return jsonify(teacher_data), 200


@app.route('/GetSchedule', methods=['GET'])
def GetSchedule():
    username = request.args.get('username')
    role = request.args.get('role', '').lower()
    if not username or not role:
        return jsonify({'error': 'Username and role are required'}), 400
    if role == 'teacher':
        teacher = db.session.execute(text("SELECT id FROM Teacher WHERE username = :username"), {"username": username}).fetchone()
        if not teacher:
            return jsonify({'error': 'Teacher not found'}), 404
        teacher_id = teacher.id
        schedule_query = text("""
            SELECT ts.id AS schedule_id, ts.day, s.slot_id, s.time, s.booked, s.sch_id, s.Course_id, c.name as course_name
            FROM TeacherSchedule ts
            LEFT JOIN Slot s ON ts.id = s.sch_id
            LEFT JOIN Course c ON s.Course_id = c.id
            WHERE ts.teacher_id = :id
            ORDER BY ts.day, s.time
        """)
        schedule = db.session.execute(schedule_query, {'id': teacher_id}).fetchall()
        schedule_list = []
        for row in schedule:
            slot_info = {
                "scheduleId": row.schedule_id,
                "day": row.day,
                "slotId": row.slot_id,
                "time": row.time,
                "isBooked": bool(row.booked) if row.booked is not None else None,
                "course": {"courseId": row.Course_id, "courseName": row.course_name} if row.Course_id else None
            }
            
            # Add student information if the slot is booked - get the specific student for this slot
            if row.booked and row.slot_id:
                student_query = text("""
                    SELECT st.username, st.name
                    FROM BookedEnrollmentSlots bes
                    JOIN Enrollment e ON bes.enrollment_id = e.id
                    JOIN Student st ON e.student_id = st.id
                    WHERE bes.slot_id = :slot_id AND e.qari_id = :teacher_id
                """)
                student = db.session.execute(student_query, {'slot_id': row.slot_id, 'teacher_id': teacher_id}).fetchone()
                if student:
                    slot_info["student"] = {
                        "username": student.username,
                        "name": student.name
                    }
            
            schedule_list.append(slot_info)
        return jsonify({'role': 'Teacher', 'schedule': schedule_list}), 200
    elif role == 'student':
        student = db.session.execute(text("SELECT id FROM Student WHERE username = :username"), {"username": username}).fetchone()
        if not student:
            return jsonify({'error': 'Student not found'}), 404
        student_id = student.id
        slots_query = text("""
            SELECT s.slot_id, s.time, ts.day, s.booked, s.sch_id, s.Course_id, c.name as course_name, 
                   t.username as teacher_username, t.name as teacher_name
            FROM BookedEnrollmentSlots bes
            JOIN Enrollment e ON bes.enrollment_id = e.id
            JOIN Slot s ON bes.slot_id = s.slot_id
            JOIN TeacherSchedule ts ON s.sch_id = ts.id
            LEFT JOIN Course c ON s.Course_id = c.id
            JOIN Teacher t ON ts.teacher_id = t.id
            WHERE e.student_id = :student_id
            ORDER BY ts.day, s.time
        """)
        slots = db.session.execute(slots_query, {"student_id": student_id}).fetchall()
        slot_list = []
        for slot in slots:
            # Check if this slot has been swapped/transferred
            swap_info = check_slot_swap_info(slot.slot_id)
            
            slot_info = {
                "slotId": slot.slot_id,
                "day": slot.day,
                "time": slot.time,
                "isBooked": bool(slot.booked),
                "course": {"courseId": slot.Course_id, "courseName": slot.course_name} if slot.Course_id else None,
                "teacher": {
                    "username": slot.teacher_username,
                    "name": slot.teacher_name
                }
            }
            
            # Add swap information if the slot was transferred
            if swap_info:
                slot_info["swapInfo"] = swap_info
            
            slot_list.append(slot_info)
        return jsonify({'role': 'Student', 'schedule': slot_list}), 200
    elif role == 'parent':
        parent = db.session.execute(text("SELECT id FROM Parent WHERE username = :username"), {"username": username}).fetchone()
        if not parent:
            return jsonify({'error': 'Parent not found'}), 404
        parent_id = parent.id
        children = db.session.execute(text("SELECT id, name FROM Student WHERE parent_id = :parent_id"), {"parent_id": parent_id}).fetchall()
        children_schedules = []
        for child in children:
            slots_query = text("""
                SELECT s.slot_id, s.time, ts.day, s.booked, s.Course_id, c.name as course_name,
                       t.username as teacher_username, t.name as teacher_name
                FROM BookedEnrollmentSlots bes
                JOIN Enrollment e ON bes.enrollment_id = e.id
                JOIN Slot s ON bes.slot_id = s.slot_id
                JOIN TeacherSchedule ts ON s.sch_id = ts.id
                LEFT JOIN Course c ON s.Course_id = c.id
                JOIN Teacher t ON ts.teacher_id = t.id
                WHERE e.student_id = :child_id
                ORDER BY ts.day, s.time
            """)
            slots = db.session.execute(slots_query, {"child_id": child.id}).fetchall()
            slot_list = []
            for slot in slots:
                slot_info = {
                    "slotId": slot.slot_id,
                    "day": slot.day,
                    "time": slot.time,
                    "isBooked": bool(slot.booked),
                    "course": {"courseId": slot.Course_id, "courseName": slot.course_name} if slot.Course_id else None,
                    "teacher": {
                        "username": slot.teacher_username,
                        "name": slot.teacher_name
                    }
                }
                slot_list.append(slot_info)
            children_schedules.append({
                'childId': child.id,
                'childName': child.name,
                'slots': slot_list
            })
        return jsonify({'role': 'Parent', 'childrenSchedules': children_schedules}), 200
    else:
        return jsonify({'error': 'Invalid role'}), 400


@app.route('/GetStudentProgress', methods=['GET'])
def GetStudentProgress():
    username = request.args.get('username')
    if not username:
        return jsonify({'error': 'Username is required'}), 400

    # Get student ID
    student = db.session.execute(text("SELECT id FROM Student WHERE username = :username"), {"username": username}).fetchone()
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    student_id = student.id

    # Get all enrollments for the student
    enrollments_query = text("""
        SELECT e.id AS enrollment_id, c.id AS course_id, c.name AS course_name
        FROM Enrollment e
        JOIN Course c ON e.course_id = c.id
        WHERE e.student_id = :student_id
    """)
    enrollments = db.session.execute(enrollments_query, {"student_id": student_id}).fetchall()

    progress_data = []
    for enroll in enrollments:
        # Get lesson progress for this course
        lesson_query = text("""
            SELECT COUNT(*) AS total_lessons,
                   SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS completed_lessons
            FROM StudentLessonProgress
            WHERE student_id = :student_id AND course_id = :course_id
        """)
        lesson_data = db.session.execute(lesson_query, {"student_id": student_id, "course_id": enroll.course_id}).fetchone()
        total = lesson_data.total_lessons or 0
        completed = lesson_data.completed_lessons or 0
        progress = int((completed / total) * 100) if total > 0 else 0

        # Get total lessons for the course (regardless of student progress)
        total_course_lessons_query = text("SELECT COUNT(*) FROM QuranLessons WHERE CourseID = :course_id")
        total_course_lessons = db.session.execute(total_course_lessons_query, {"course_id": enroll.course_id}).scalar() or 0

        progress_data.append({
            "courseId": enroll.course_id,
            "courseName": enroll.course_name,
            "totalLessons": total,
            "completedLessons": completed,
            "progressPercent": progress,
            "totalCourseLessons": total_course_lessons
        })

    return jsonify({"username": username, "progress": progress_data}), 200


@app.route('/GetCourseLessons', methods=['GET'])
def GetCourseLessons():
    username = request.args.get('username')
    course_id = request.args.get('courseId')
    if not username or not course_id:
        return jsonify({'error': 'Username and courseId are required'}), 400

    # Get student ID
    student = db.session.execute(text("SELECT id FROM Student WHERE username = :username"), {"username": username}).fetchone()
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    student_id = student.id

    # Get all lessons for the course
    lessons_query = text("""
        SELECT ql.ID AS id, CONCAT(s.SurahName, ' (Ruku ', ql.RukuID, ')') AS name
        FROM QuranLessons ql
        JOIN Surah s ON ql.SurahNo = s.SurahNo
        WHERE ql.CourseID = :course_id
        ORDER BY ql.ID
    """)
    lessons = db.session.execute(lessons_query, {"course_id": course_id}).fetchall()

    # Get completed status for each lesson for this student
    lesson_status_query = text("""
        SELECT lesson_id, status
        FROM StudentLessonProgress
        WHERE student_id = :student_id AND course_id = :course_id
    """)
    status_rows = db.session.execute(lesson_status_query, {"student_id": student_id, "course_id": course_id}).fetchall()
    status_map = {row.lesson_id: row.status for row in status_rows}

    lesson_list = []
    for lesson in lessons:
        lesson_list.append({
            "lessonId": lesson.id,
            "title": lesson.name,
            "completed": bool(status_map.get(lesson.id, 0) == 1)
        })

    return jsonify({
        "username": username,
        "courseId": course_id,
        "lessons": lesson_list
    }), 200


@app.route("/GetTeacherCourses", methods=["GET"])
def GetTeacherCourses():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get teacher ID
    teacher = db.session.execute(text("SELECT id FROM Teacher WHERE username = :username"), {"username": username}).fetchone()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404
    teacher_id = teacher.id

    # Fetch courses and student count per course
    query = text("""
        SELECT c.id AS course_id, c.name AS course_name, c.description AS course_description, COUNT(e.student_id) AS student_count
        FROM TeacherCourse tc
        JOIN Course c ON tc.course_id = c.id
        LEFT JOIN Enrollment e ON e.course_id = c.id AND e.qari_id = :teacher_id
        WHERE tc.qari_id = :teacher_id
        GROUP BY c.id, c.name, c.description
    """)
    results = db.session.execute(query, {"teacher_id": teacher_id}).fetchall()
    courses = []
    for row in results:
        courses.append({
            "courseId": row.course_id,
            "courseName": row.course_name,
            "courseDescription": row.course_description,
            "studentCount": row.student_count
        })
    return jsonify({"courses": courses}), 200


@app.route("/GetTeacherStudents", methods=["GET"])
def GetTeacherStudents():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get teacher ID
    teacher = db.session.execute(text("SELECT id FROM Teacher WHERE username = :username"), {"username": username}).fetchone()
    if not teacher:
        return jsonify({"error": "Teacher not found"}), 404
    teacher_id = teacher.id

    # Get all courses taught by this teacher
    courses_query = text("""
        SELECT c.id AS course_id, c.name AS course_name, c.description AS course_description
        FROM TeacherCourse tc
        JOIN Course c ON tc.course_id = c.id
        WHERE tc.qari_id = :teacher_id
    """)
    courses = db.session.execute(courses_query, {"teacher_id": teacher_id}).fetchall()
    result = []
    for course in courses:
        # Get all students enrolled in this course with this teacher
        students_query = text("""
            SELECT s.id AS student_id, s.username, s.name, s.region, s.gender, s.dob, s.pic
            FROM Enrollment e
            JOIN Student s ON e.student_id = s.id
            WHERE e.qari_id = :teacher_id AND e.course_id = :course_id
        """)
        students = db.session.execute(students_query, {"teacher_id": teacher_id, "course_id": course.course_id}).fetchall()
        student_list = []
        for student in students:
            # Get lesson progress for this student in this course
            lesson_progress_query = text("""
                SELECT COUNT(*) AS total_lessons,
                       SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS completed_lessons
                FROM StudentLessonProgress
                WHERE student_id = :student_id AND course_id = :course_id
            """)
            progress_row = db.session.execute(lesson_progress_query, {"student_id": student.student_id, "course_id": course.course_id}).fetchone()
            total_lessons = progress_row.total_lessons or 0
            completed_lessons = progress_row.completed_lessons or 0
            percent_complete = int((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0
            student_list.append({
                "studentId": student.student_id,
                "username": student.username,
                "name": student.name,
                "region": student.region,
                "gender": student.gender,
                "dob": str(student.dob) if student.dob else None,
                "avatar": student.pic,
                "lessonsCompleted": completed_lessons,
                "totalLessons": total_lessons,
                "courseCompletionPercent": percent_complete
            })
        result.append({
            "courseId": course.course_id,
            "courseName": course.course_name,
            "courseDescription": course.course_description,
            "students": student_list
        })
    return jsonify({"courses": result}), 200


# --- Slot Incharge/Swap Request Endpoints ---

@app.route('/RequestIncharge', methods=['POST'])
def request_incharge():
    body = request.json
    from_teacher_username = body.get('fromTeacher')
    to_teacher_username = body.get('toTeacher')
    slot_ids = body.get('slotIds', [])
    note = body.get('note', '')
    if not from_teacher_username or not to_teacher_username or not slot_ids:
        return jsonify({'error': 'Missing required fields'}), 400
    # Get teacher IDs
    from_teacher = db.session.execute(text("SELECT id FROM Teacher WHERE username = :u"), {'u': from_teacher_username}).fetchone()
    to_teacher = db.session.execute(text("SELECT id FROM Teacher WHERE username = :u"), {'u': to_teacher_username}).fetchone()
    if not from_teacher or not to_teacher:
        return jsonify({'error': 'Invalid teacher username(s)'}), 400
    from_teacher_id = from_teacher.id
    to_teacher_id = to_teacher.id
    slot_ids_str = ','.join(str(sid) for sid in slot_ids)
    try:
        db.session.execute(text("""
            INSERT INTO SlotInchargeRequest (from_teacher_id, to_teacher_id, slot_ids, status, created_at)
            VALUES (:from_teacher_id, :to_teacher_id, :slot_ids, 'pending', GETDATE())
        """), {
            'from_teacher_id': from_teacher_id,
            'to_teacher_id': to_teacher_id,
            'slot_ids': slot_ids_str
        })
        db.session.commit()
        return jsonify({'message': 'Request sent successfully'}), 201
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to send request', 'details': str(e)}), 500

@app.route('/GetInchargeRequests', methods=['GET'])
def get_incharge_requests():
    username = request.args.get('username')
    if not username:
        return jsonify({'error': 'Username is required'}), 400
    teacher = db.session.execute(text("SELECT id FROM Teacher WHERE username = :u"), {'u': username}).fetchone()
    if not teacher:
        return jsonify({'error': 'Teacher not found'}), 404
    teacher_id = teacher.id
    # Get incoming requests
    requests = db.session.execute(text("""
        SELECT r.id, t1.username AS from_teacher, t2.username AS to_teacher, r.slot_ids, r.status, r.created_at, r.responded_at, r.from_teacher_id
        FROM SlotInchargeRequest r
        JOIN Teacher t1 ON r.from_teacher_id = t1.id
        JOIN Teacher t2 ON r.to_teacher_id = t2.id
        WHERE r.to_teacher_id = :tid
        ORDER BY r.created_at DESC
    """), {'tid': teacher_id}).fetchall()
    result = []
    for row in requests:
        slot_ids = [int(sid) for sid in row.slot_ids.split(',') if sid]
        slot_details = []
        for slot_id in slot_ids:
            slot_row = db.session.execute(text("""
                SELECT s.slot_id, ts.day, s.time, s.booked, s.Course_id, c.name as course_name
                FROM Slot s
                JOIN TeacherSchedule ts ON s.sch_id = ts.id
                LEFT JOIN Course c ON s.Course_id = c.id
                WHERE s.slot_id = :slot_id
            """), {'slot_id': slot_id}).fetchone()
            if slot_row:
                slot_details.append({
                    'slotId': slot_row.slot_id,
                    'day': slot_row.day,
                    'time': slot_row.time,
                    'isBooked': bool(slot_row.booked),
                    'course': {"courseId": slot_row.Course_id, "courseName": slot_row.course_name} if slot_row.Course_id else None
                })
        result.append({
            'requestId': row.id,
            'fromTeacher': row.from_teacher,
            'toTeacher': row.to_teacher,
            'slots': slot_details,
            'status': row.status,
            'createdAt': str(row.created_at),
            'respondedAt': str(row.responded_at) if row.responded_at else None
        })
    return jsonify({'requests': result}), 200

@app.route('/RespondInchargeRequest', methods=['POST'])
def respond_incharge_request():
    body = request.json
    request_id = body.get('requestId')
    response = body.get('response')  # 'accept' or 'decline'
    if not request_id or response not in ('accept', 'decline'):
        return jsonify({'error': 'Missing or invalid fields'}), 400
    # Get the request
    req = db.session.execute(text("SELECT * FROM SlotInchargeRequest WHERE id = :id"), {'id': request_id}).fetchone()
    if not req:
        return jsonify({'error': 'Request not found'}), 404
    if req.status != 'pending':
        return jsonify({'error': 'Request already responded'}), 400
    try:
        if response == 'accept':
            # Transfer slot ownership: update Slot.sch_id to the new teacher's schedule
            slot_ids = [int(sid) for sid in req.slot_ids.split(',') if sid]
            # Find the to_teacher's schedule ids for each slot's day
            for slot_id in slot_ids:
                # Get slot info
                slot = db.session.execute(text("SELECT sch_id FROM Slot WHERE slot_id = :sid"), {'sid': slot_id}).fetchone()
                if not slot:
                    continue
                # Get the day for this slot's schedule
                sch = db.session.execute(text("SELECT day FROM TeacherSchedule WHERE id = :sch_id"), {'sch_id': slot.sch_id}).fetchone()
                if not sch:
                    continue
                # Find or create a schedule for the to_teacher for this day
                to_sch = db.session.execute(text("SELECT id FROM TeacherSchedule WHERE teacher_id = :tid AND day = :day"), {'tid': req.to_teacher_id, 'day': sch.day}).fetchone()
                if not to_sch:
                    # Create schedule for this day
                    new_sch = db.session.execute(text("INSERT INTO TeacherSchedule (day, teacher_id) OUTPUT inserted.id VALUES (:day, :tid)"), {'day': sch.day, 'tid': req.to_teacher_id})
                    to_sch_id = new_sch.scalar()
                else:
                    to_sch_id = to_sch.id
                # Update slot to new schedule
                db.session.execute(text("UPDATE Slot SET sch_id = :new_sch_id WHERE slot_id = :slot_id"), {'new_sch_id': to_sch_id, 'slot_id': slot_id})
        # Update request status
        db.session.execute(text("UPDATE SlotInchargeRequest SET status = :status, responded_at = GETDATE() WHERE id = :id"), {'status': response, 'id': request_id})
        db.session.commit()
        return jsonify({'message': f'Request {response}ed successfully'}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to respond to request', 'details': str(e)}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    print("UNCAUGHT EXCEPTION:", e)
    traceback.print_exc()
    return jsonify({"error": "Internal server error", "details": str(e)}), 500



def get_user_region(role, username):
    role = role.lower()
    if role == "teacher":
        query = text("SELECT region FROM Teacher WHERE username = :username")
    elif role == "parent":
        query = text("SELECT region FROM Parent WHERE username = :username")
    elif role == "student":
        query = text("SELECT region FROM Student WHERE username = :username")
    else:
        return None
    result = db.session.execute(query, {"username": username}).fetchone()
    if result:
        return result.region
    return None

@app.route('/api/get_user_region', methods=['GET'])
def api_get_user_region():
    role = request.args.get('role', '').lower()
    username = request.args.get('username', '')
    if not role or not username:
        return jsonify({'error': 'role and username are required'}), 400
    region = get_user_region(role, username)
    if region is None:
        return jsonify({'error': 'Region not found for user'}), 404
    return jsonify({'region': region})

def check_slot_swap_info(slot_id):

    # Check if this slot was part of an accepted transfer request
    swap_query = text("""
        SELECT 
            r.id as request_id,
            t1.username as original_teacher,
            t2.username as new_teacher,
            r.created_at,
            r.responded_at
        FROM SlotInchargeRequest r
        JOIN Teacher t1 ON r.from_teacher_id = t1.id
        JOIN Teacher t2 ON r.to_teacher_id = t2.id
        WHERE r.status = 'accept' 
        AND r.slot_ids LIKE :slot_id_pattern
    """)
    
    # Create pattern to match slot_id in the comma-separated list
    slot_id_pattern = f'%{slot_id}%'
    result = db.session.execute(swap_query, {'slot_id_pattern': slot_id_pattern}).fetchone()
    
    if result:
        return {
            'requestId': result.request_id,
            'originalTeacher': result.original_teacher,
            'newTeacher': result.new_teacher,
            'transferDate': str(result.responded_at) if result.responded_at else str(result.created_at),
            'isSwapped': True
        }
    return None

@app.route("/GetParentChildren", methods=["GET"])
def GetParentChildren():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "Username is required"}), 400

    # Get parent id from username
    parent = db.session.execute(
        text("SELECT id FROM Parent WHERE username = :username"),
        {"username": username}
    ).fetchone()
    if not parent:
        return jsonify({"error": "Parent not found"}), 404

    parent_id = parent.id

    # Get all children for this parent
    children = db.session.execute(text("""
        SELECT 
            s.id,
            s.name,
            s.username,
            s.pic AS avatar,
            s.dob,
            s.gender,
            s.region
        FROM Student s
        WHERE s.parent_id = :parent_id
        ORDER BY s.name
    """), {"parent_id": parent_id}).fetchall()

    children_list = []
    for child in children:
        dob = child.dob
        age = None
        if dob:
            today = datetime.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        # Fetch courses for this child
        courses = db.session.execute(text("""
            SELECT c.id, c.name, c.description
            FROM Enrollment e
            JOIN Course c ON e.course_id = c.id
            WHERE e.student_id = :student_id
        """), {"student_id": child.id}).fetchall()
        courses_list = [
            {
                "id": course.id,
                "name": course.name,
                "description": course.description
            }
            for course in courses
        ]

        # Fetch booked slots for this child
        slots = db.session.execute(text("""
            SELECT s.slot_id, s.time, ts.day, s.booked, s.sch_id, s.Course_id, c.name as course_name, 
                   t.username as teacher_username, t.name as teacher_name
            FROM BookedEnrollmentSlots bes
            JOIN Enrollment e ON bes.enrollment_id = e.id
            JOIN Slot s ON bes.slot_id = s.slot_id
            JOIN TeacherSchedule ts ON s.sch_id = ts.id
            LEFT JOIN Course c ON s.Course_id = c.id
            JOIN Teacher t ON ts.teacher_id = t.id
            WHERE e.student_id = :student_id
            ORDER BY ts.day, s.time
        """), {"student_id": child.id}).fetchall()
        slots_list = [
            {
                "slotId": slot.slot_id,
                "day": slot.day,
                "time": slot.time,
                "isBooked": bool(slot.booked),
                "course": {"courseId": slot.Course_id, "courseName": slot.course_name} if slot.Course_id else None,
                "teacher": {
                    "username": slot.teacher_username,
                    "name": slot.teacher_name
                }
            }
            for slot in slots
        ]

        children_list.append({
            "id": child.id,
            "name": child.name,
            "username": child.username,
            "avatar": child.avatar or "/placeholder.svg",
            "age": age,
            "gender": child.gender,
            "region": child.region,
            "courses": courses_list,
            "slots": slots_list  # <-- Add slots here!
        })

    return jsonify({"children": children_list}), 200

@app.route('/agora/token', methods=['GET'])
def generate_agora_token():
    channel_name = request.args.get('channel')
    uid = request.args.get('uid', '0')  # '0' means let Agora assign a UID
    role = request.args.get('role', 'publisher')  # or 'subscriber'
    expire_time_seconds = 3600  # 1 hour

    if not channel_name:
        return jsonify({'error': 'Channel name is required'}), 400

    # Agora roles: 1 = publisher, 2 = subscriber
    if role == 'publisher':
        agora_role = 1
    else:
        agora_role = 2

    current_timestamp = int(datetime.utcnow().timestamp())
    privilege_expired_ts = current_timestamp + expire_time_seconds

    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID, AGORA_APP_CERTIFICATE,
        channel_name, int(uid), agora_role, privilege_expired_ts
    )

    return jsonify({
        'appId': AGORA_APP_ID,
        'token': token,
        'channel': channel_name,
        'uid': uid,
        'expireAt': privilege_expired_ts
    })

# Start a video call session
@app.route('/api/video-call/start', methods=['POST'])
def start_video_call():
    data = request.json
    teacher_id = data.get('teacherId')
    student_id = data.get('studentId')
    slot_id = data.get('slotId')
    room_id = data.get('roomId')
    course_id = data.get('courseId')
    now = datetime.utcnow()
    if not all([teacher_id, student_id, slot_id, room_id, course_id]):
        return jsonify({'error': 'Missing required fields'}), 400

    # If teacher_id or student_id are strings (usernames), look up their IDs
    if isinstance(teacher_id, str) and not teacher_id.isdigit():
        teacher_id_lookup = db.session.execute(
            text("SELECT id FROM Teacher WHERE username = :username"),
            {"username": teacher_id}
        ).fetchone()
        if not teacher_id_lookup:
            return jsonify({'error': 'Teacher username not found'}), 404
        teacher_id = teacher_id_lookup.id
    if isinstance(student_id, str) and not student_id.isdigit():
        student_id_lookup = db.session.execute(
            text("SELECT id FROM Student WHERE username = :username"),
            {"username": student_id}
        ).fetchone()
        if not student_id_lookup:
            return jsonify({'error': 'Student username not found'}), 404
        student_id = student_id_lookup.id

    insert_query = text('''
        INSERT INTO VideoCallSession
            (TeacherID, StudentID, SlotID, RoomID, CourseId, CallStartTime, Status, CreatedAt)
        OUTPUT inserted.SessionID
        VALUES
            (:teacher_id, :student_id, :slot_id, :room_id, :course_id, :call_start_time, 'started', :created_at)
    ''')
    session_id = db.session.execute(insert_query, {
        'teacher_id': teacher_id,
        'student_id': student_id,
        'slot_id': slot_id,
        'room_id': room_id,
        'course_id': course_id,
        'call_start_time': now,
        'created_at': now
    }).scalar()
    db.session.commit()
    session = db.session.execute(text("SELECT * FROM VideoCallSession WHERE SessionID = :session_id"), {"session_id": session_id}).fetchone()
    return jsonify(dict(session._mapping)), 201

# Check for active call
@app.route('/api/video-call/active', methods=['GET'])
def check_active_video_call():
    student_id = request.args.get('studentId')
    slot_id = request.args.get('slotId')
    if not student_id or not slot_id:
        return jsonify({'error': 'studentId and slotId are required'}), 400

    # If student_id is not an integer, look up by username
    if isinstance(student_id, str) and not student_id.isdigit():
        student_id_lookup = db.session.execute(
            text("SELECT id FROM Student WHERE username = :username"),
            {"username": student_id}
        ).fetchone()
        if not student_id_lookup:
            return jsonify({'error': 'Student username not found'}), 404
        student_id = student_id_lookup.id

    session = db.session.execute(text('''
        SELECT * FROM VideoCallSession
        WHERE StudentID = :student_id AND SlotID = :slot_id AND Status = 'started'
    '''), {'student_id': student_id, 'slot_id': slot_id}).fetchone()
    return jsonify({'active': bool(session), 'session': dict(session._mapping) if session else None})

# End a video call session
@app.route('/api/video-call/end', methods=['POST'])
def end_video_call():
    data = request.json
    session_id = data.get('sessionId')
    call_end_time = data.get('callEndTime')
    if not session_id:
        return jsonify({'error': 'sessionId is required'}), 400
    session = db.session.execute(text("SELECT * FROM VideoCallSession WHERE SessionID = :session_id"), {"session_id": session_id}).fetchone()
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    now = datetime.utcnow() if not call_end_time else datetime.fromisoformat(call_end_time)
    db.session.execute(text('''
        UPDATE VideoCallSession
        SET Status = 'ended', CallEndTime = :call_end_time
        WHERE SessionID = :session_id
    '''), {'call_end_time': now, 'session_id': session_id})
    db.session.commit()
    # Return info for rating prompt
    return jsonify({
        'success': True,
        'askForRating': True,
        'sessionId': session.SessionID,
        'teacherId': session.TeacherID,
        'studentId': session.StudentID
    })

# --- Teacher Rating Endpoint ---
@app.route('/api/teacher-rating', methods=['POST'])
def submit_teacher_rating():
    data = request.json
    session_id = data.get('sessionId')
    teacher_id = data.get('teacherId')
    student_id = data.get('studentId')
    rating_value = data.get('ratingValue')
    if not all([session_id, teacher_id, student_id, rating_value]):
        return jsonify({'error': 'sessionId, teacherId, studentId, and ratingValue are required'}), 400
    try:
        db.session.execute(text('''
            INSERT INTO TeacherRating (SessionID, TeacherID, StudentID, RatingValue, RatedAt)
            VALUES (:session_id, :teacher_id, :student_id, :rating_value, :rated_at)
        '''), {
            'session_id': session_id,
            'teacher_id': teacher_id,
            'student_id': student_id,
            'rating_value': rating_value,
            'rated_at': datetime.utcnow()
        })
        # Calculate new average rating for the teacher
        avg_rating = db.session.execute(
            text("SELECT AVG(CAST(RatingValue AS FLOAT)) FROM TeacherRating WHERE TeacherID = :teacher_id"),
            {'teacher_id': teacher_id}
        ).scalar()
        # Update Teacher.ratings column (rounded to 1 decimal place)
        rounded_avg = round(avg_rating, 1) if avg_rating is not None else None
        db.session.execute(
            text("UPDATE Teacher SET ratings = :avg_rating WHERE id = :teacher_id"),
            {'avg_rating': rounded_avg, 'teacher_id': teacher_id}
        )
        db.session.commit()
        return jsonify({'success': True, 'message': 'Rating submitted successfully.'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to submit rating', 'details': str(e)}), 500

# Utility function to store all booked slots in VideoCallSession
@app.route('/storing-classes', methods=['POST'])
def store_booked_slots_in_videocallsession():
    # Find all slots that are booked
    slots = db.session.execute(text('''
        SELECT s.slot_id, s.sch_id, s.Course_id, s.booked, ts.teacher_id, e.student_id
        FROM Slot s
        JOIN TeacherSchedule ts ON s.sch_id = ts.id
        LEFT JOIN Enrollment e ON e.qari_id = ts.teacher_id AND e.course_id = s.Course_id
        WHERE s.booked = 1
    ''')).fetchall()
    now = datetime.utcnow()
    inserted = 0
    for slot in slots:
        # Check if a VideoCallSession already exists for this slot
        exists = db.session.execute(text('''
            SELECT 1 FROM VideoCallSession WHERE SlotID = :slot_id
        '''), {'slot_id': slot.slot_id}).fetchone()
        if exists:
            continue
        # Insert new VideoCallSession
        db.session.execute(text('''
            INSERT INTO VideoCallSession (TeacherID, StudentID, SlotID, CourseId, RoomID, Status, CreatedAt)
            VALUES (:teacher_id, :student_id, :slot_id, :course_id, :room_id, 'scheduled', :created_at)
        '''), {
            'teacher_id': slot.teacher_id,
            'student_id': slot.student_id,
            'slot_id': slot.slot_id,
            'course_id': slot.Course_id,
            'room_id': f"slot-{slot.slot_id}",
            'created_at': now
        })
        inserted += 1
    db.session.commit()
    return inserted

@app.route('/GetRukuText', methods=['GET'])
def get_ruku_text():
    # Get surah_name and ruku_id from query params
    surah_name = request.args.get('surah_name')
    ruku_id = request.args.get('ruku_id', type=int)
    if not surah_name or not ruku_id:
        return jsonify({'error': 'surah_name and ruku_id are required'}), 400

    # 1. Get SurahNo from SurahName
    surah_row = db.session.execute(text("""
        SELECT SurahNo FROM Surah WHERE SurahName = :surah_name
    """), {'surah_name': surah_name}).fetchone()
    if not surah_row:
        return jsonify({'error': 'Surah name not found'}), 404
    surah_no = surah_row.SurahNo

    # 2. Get Ruku range
    ruku_row = db.session.execute(text("""
        SELECT StartingAyahNo, EndingAyahNo
        FROM Ruku
        WHERE SurahNo = :surah_no AND RukuNo = :ruku_id
    """), {'surah_no': surah_no, 'ruku_id': ruku_id}).fetchone()

    if not ruku_row:
        return jsonify({'error': 'Ruku not found'}), 404

    start_ayah, end_ayah = ruku_row.StartingAyahNo, ruku_row.EndingAyahNo

    # 3. Get Ayahs from Quran table
    ayahs = db.session.execute(text("""
        SELECT VerseID, AyahText
        FROM Quran
        WHERE SuraID = :surah_no AND VerseID BETWEEN :start_ayah AND :end_ayah
        ORDER BY VerseID
    """), {'surah_no': surah_no, 'start_ayah': start_ayah, 'end_ayah': end_ayah}).fetchall()

    ayah_list = [{'verse': row.VerseID, 'text': row.AyahText} for row in ayahs]

    return jsonify({
        'surah_no': surah_no,
        'surah_name': surah_name,
        'ruku_id': ruku_id,
        'start_ayah': start_ayah,
        'end_ayah': end_ayah,
        'ayahs': ayah_list
    })

# --- New Endpoints for Per-Student Bookmarks and Status ---
from flask import request, jsonify
from sqlalchemy import text

@app.route('/api/lesson-details', methods=['GET'])
def get_lesson_details():
    role = request.args.get('role')
    username = request.args.get('username')
    surah_name = request.args.get('surah_name')
    ruku_id = request.args.get('ruku_id', type=int)
    teacher_username = request.args.get('teacher_username')
    course_id = request.args.get('course_id')

    print("DEBUG:", role, username, surah_name, ruku_id, course_id, teacher_username)
    if not role or not username or not surah_name or not ruku_id or not teacher_username or not course_id:
        return jsonify({'error': 'role, username, surah_name, ruku_id, teacher_username, and course_id are required'}), 400

    # 1. Get user id (student/teacher/parent)
    if role.lower() == 'student':
        user_row = db.session.execute(text("SELECT id FROM Student WHERE username = :u"), {'u': username}).fetchone()
        if not user_row:
            return jsonify({'error': 'Student not found'}), 404
        student_id = user_row.id
    elif role.lower() == 'parent':
        user_row = db.session.execute(text("SELECT id FROM Student WHERE username = :u"), {'u': username}).fetchone()
        if not user_row:
            return jsonify({'error': 'Student (child) not found'}), 404
        student_id = user_row.id
    elif role.lower() == 'teacher':
        student_username = request.args.get('student_username')
        if not student_username:
            return jsonify({'error': 'student_username required for teacher'}), 400
        user_row = db.session.execute(text("SELECT id FROM Student WHERE username = :u"), {'u': student_username}).fetchone()
        if not user_row:
            return jsonify({'error': 'Student not found'}), 404
        student_id = user_row.id
    else:
        return jsonify({'error': 'Invalid role'}), 400

    # 2. Get SurahNo
    surah_row = db.session.execute(text("SELECT SurahNo FROM Surah WHERE SurahName = :name"), {'name': surah_name}).fetchone()
    if not surah_row:
        return jsonify({'error': 'Surah not found'}), 404
    surah_no = surah_row.SurahNo

    # 3. Get lesson_id and course_id
    lesson_row = db.session.execute(
        text("SELECT ID, CourseID FROM QuranLessons WHERE SurahNo = :surah_no AND RukuID = :ruku_id AND CourseID = :course_id"),
        {'surah_no': surah_no, 'ruku_id': ruku_id, 'course_id': course_id}
    ).fetchone()
    if not lesson_row:
        return jsonify({'error': 'Lesson not found'}), 404
    lesson_id = lesson_row.ID

    # 4. Get teacher_id from teacher_username
    teacher_row = db.session.execute(text("SELECT id FROM Teacher WHERE username = :username"), {'username': teacher_username}).fetchone()
    teacher_id = teacher_row.id if teacher_row else None

    # 5. Get StudentLessonProgress row
    slp_row = db.session.execute(text("""
        SELECT status, AyahPointer FROM StudentLessonProgress
        WHERE student_id = :student_id AND lesson_id = :lesson_id AND course_id = :course_id AND teacher_id = :teacher_id
    """), {'student_id': student_id, 'lesson_id': lesson_id, 'course_id': course_id, 'teacher_id': teacher_id}).fetchone()
    status = slp_row.status if slp_row else 0
    ayah_pointer = slp_row.AyahPointer if slp_row else None

    # 6. Get Ruku range
    ruku_row = db.session.execute(text("""
        SELECT StartingAyahNo, EndingAyahNo
        FROM Ruku
        WHERE SurahNo = :surah_no AND RukuNo = :ruku_id
    """), {'surah_no': surah_no, 'ruku_id': ruku_id}).fetchone()
    if not ruku_row:
        return jsonify({'error': 'Ruku not found'}), 404
    start_ayah, end_ayah = ruku_row.StartingAyahNo, ruku_row.EndingAyahNo

    # 7. Get Quranic text
    ayahs = db.session.execute(text("""
        SELECT VerseID, AyahText
        FROM Quran
        WHERE SuraID = :surah_no AND VerseID BETWEEN :start_ayah AND :end_ayah
        ORDER BY VerseID
    """), {'surah_no': surah_no, 'start_ayah': start_ayah, 'end_ayah': end_ayah}).fetchall()
    ayah_list = [{'verse': row.VerseID, 'text': row.AyahText} for row in ayahs]

    return jsonify({
        'surah_name': surah_name,
        'ruku_id': ruku_id,
        'ayahs': ayah_list,
        'status': status,
        'bookmark': ayah_pointer
    })

@app.route('/api/lesson-bookmark', methods=['POST'])
def set_lesson_bookmark():
    data = request.json
    username = data.get('username')
    surah_name = data.get('surah_name')
    ruku_id = data.get('ruku_id')
    ayah_no = data.get('ayah_no')
    teacher_username = data.get('teacher_username')
    course_id = data.get('course_id')
    
    if not username or not surah_name or not ruku_id or not ayah_no or not teacher_username or not course_id:
        return jsonify({'error': 'username, surah_name, ruku_id, ayah_no, teacher_username, and course_id are required'}), 400
    
    try:
        # Optimized: Combine multiple queries into one for better performance
        combined_query = text("""
            SELECT 
                s.id as student_id,
                su.SurahNo,
                ql.ID as lesson_id,
                t.id as teacher_id
            FROM Student s
            JOIN Surah su ON su.SurahName = :surah_name
            JOIN QuranLessons ql ON ql.SurahNo = su.SurahNo AND ql.RukuID = :ruku_id AND ql.CourseID = :course_id
            JOIN Teacher t ON t.username = :teacher_username
            WHERE s.username = :username
        """)
        
        result = db.session.execute(combined_query, {
            'username': username,
            'surah_name': surah_name,
            'ruku_id': ruku_id,
            'course_id': course_id,
            'teacher_username': teacher_username
        }).fetchone()
        
        if not result:
            return jsonify({'error': 'Student, lesson, or teacher not found'}), 404
            
        student_id = result.student_id
        lesson_id = result.lesson_id
        teacher_id = result.teacher_id
        
        # Optimized: Use UPSERT pattern for better performance
        upsert_query = text("""
            MERGE StudentLessonProgress AS target
            USING (SELECT :student_id as student_id, :lesson_id as lesson_id) AS source
            ON target.student_id = source.student_id AND target.lesson_id = source.lesson_id
            WHEN MATCHED THEN
                UPDATE SET AyahPointer = :ayah_no, teacher_id = :teacher_id
            WHEN NOT MATCHED THEN
                INSERT (student_id, lesson_id, course_id, teacher_id, AyahPointer)
                VALUES (:student_id, :lesson_id, :course_id, :teacher_id, :ayah_no);
        """)
        
        db.session.execute(upsert_query, {
            'student_id': student_id,
            'lesson_id': lesson_id,
            'course_id': course_id,
            'teacher_id': teacher_id,
            'ayah_no': ayah_no
        })
        
        db.session.commit()
        
        # Emit socket event for real-time updates
        socketio.emit(
            'bookmark_update',
            {
                'student_id': student_id,
                'lesson_id': lesson_id,
                'course_id': course_id,
                'teacher_id': teacher_id,
                'ayah_no': ayah_no,
                'timestamp': datetime.utcnow().isoformat()
            },
            room=f"student_{student_id}"
        )
        
        return jsonify({
            'success': True, 
            'bookmark': ayah_no,
            'student_id': student_id,
            'lesson_id': lesson_id
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Bookmark error: {e}")
        return jsonify({'error': 'Failed to update bookmark', 'details': str(e)}), 500

@app.route('/api/lesson-status', methods=['POST'])
def set_lesson_status():
    data = request.json
    student_username = data.get('student_username')
    surah_name = data.get('surah_name')
    course_id = data.get('course_id')
    ruku_id = data.get('ruku_id')
    status = data.get('status')
    teacher_username = data.get('teacher_username')
    print("DEBUG:", student_username, surah_name, ruku_id, course_id, teacher_username, status)

    if not student_username or not surah_name or not ruku_id or status is None or not teacher_username or not course_id:
        return jsonify({'error': 'student_username, surah_name, ruku_id, course_id, teacher_username, and status are required'}), 400
    
    try:
        # Optimized: Combine multiple queries into one for better performance
        combined_query = text("""
            SELECT 
                s.id as student_id,
                su.SurahNo,
                ql.ID as lesson_id,
                t.id as teacher_id
            FROM Student s
            JOIN Surah su ON su.SurahName = :surah_name
            JOIN QuranLessons ql ON ql.SurahNo = su.SurahNo AND ql.RukuID = :ruku_id AND ql.CourseID = :course_id
            JOIN Teacher t ON t.username = :teacher_username
            WHERE s.username = :student_username
        """)
        
        result = db.session.execute(combined_query, {
            'student_username': student_username,
            'surah_name': surah_name,
            'ruku_id': ruku_id,
            'course_id': course_id,
            'teacher_username': teacher_username
        }).fetchone()
        
        if not result:
            return jsonify({'error': 'Student, lesson, or teacher not found'}), 404
            
        student_id = result.student_id
        lesson_id = result.lesson_id
        teacher_id = result.teacher_id
        
        # Optimized: Use UPSERT pattern for better performance
        upsert_query = text("""
            MERGE StudentLessonProgress AS target
            USING (SELECT :student_id as student_id, :lesson_id as lesson_id) AS source
            ON target.student_id = source.student_id AND target.lesson_id = source.lesson_id
            WHEN MATCHED THEN
                UPDATE SET status = :status, teacher_id = :teacher_id
            WHEN NOT MATCHED THEN
                INSERT (student_id, lesson_id, course_id, teacher_id, status)
                VALUES (:student_id, :lesson_id, :course_id, :teacher_id, :status);
        """)
        
        db.session.execute(upsert_query, {
            'student_id': student_id,
            'lesson_id': lesson_id,
            'course_id': course_id,
            'teacher_id': teacher_id,
            'status': status
        })
        
        db.session.commit()
        
        # Emit socket event for real-time updates
        socketio.emit(
            'lesson_status_update',
            {
                'student_id': student_id,
                'lesson_id': lesson_id,
                'course_id': course_id,
                'teacher_id': teacher_id,
                'status': status,
                'timestamp': datetime.utcnow().isoformat()
            },
            room=f"student_{student_id}"
        )
        
        return jsonify({
            'success': True, 
            'status': status,
            'student_id': student_id,
            'lesson_id': lesson_id
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Lesson status error: {e}")
        return jsonify({'error': 'Failed to update lesson status', 'details': str(e)}), 500

@app.route("/GetStudentTeacher", methods=["GET"])
def GetStudentTeacher():
    username = request.args.get("username")
    course_id = request.args.get("courseId")  # Accept courseId as a query param
    if not username or not course_id:
        return jsonify({"error": "Username and courseId are required"}), 400

    # Get student ID
    student = db.session.execute(
        text("SELECT id FROM Student WHERE username = :username"),
        {"username": username}
    ).fetchone()
    if not student:
        return jsonify({"error": "Student not found"}), 404
    student_id = student.id

    # Get the teacher for this student and course
    teacher = db.session.execute(text("""
        SELECT TOP 1 t.id, t.username, t.name, t.region, t.gender, t.pic, t.qualification, t.bio
        FROM Enrollment e
        JOIN Teacher t ON e.qari_id = t.id
        WHERE e.student_id = :student_id AND e.course_id = :course_id
    """), {"student_id": student_id, "course_id": course_id}).fetchone()

    if not teacher:
        return jsonify({"error": "Teacher not found for this course"}), 404

    teacher_data = {
        "id": teacher.id,
        "username": teacher.username,
        "name": teacher.name,
        "region": teacher.region,
        "gender": teacher.gender,
        "avatar": teacher.pic,
        "qualification": teacher.qualification,
        "bio": teacher.bio
    }

    return jsonify({"teacher": teacher_data}), 200

@socketio.on('join')
def on_join(data):
    student_id = data.get('student_id')
    if student_id:
        join_room(f"student_{student_id}")
        emit('joined', {'room': f"student_{student_id}"})

@socketio.on('leave')
def on_leave(data):
    student_id = data.get('student_id')
    if student_id:
        leave_room(f"student_{student_id}")
        emit('left', {'room': f"student_{student_id}"})

if __name__ == '__main__':
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)