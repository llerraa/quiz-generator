# QBank Remote Manager

QBank Remote Manager is a local Moodle plugin that extends the Moodle Web Services API to allow **remote management of the Question Bank and Quizzes**.

It is primarily designed for integrations with external systems that need to:
- upload questions into Moodle Question Bank,
- create quizzes programmatically,
- assign imported questions to quizzes,
- retrieve available question categories.

The plugin uses **standard Moodle core APIs** and respects Moodle capability and context checks.

---

## Features

- Upload questions to the Moodle Question Bank using XML format
- Create a quiz programmatically in a selected course and section
- Automatically add imported questions to the quiz
- Retrieve question bank categories for a course
- Web service–based API suitable for external integrations
- Compatible with Moodle 4.1+

---

## Provided Web Services

### 1. `local_qbankremotemanager_am_i_here`
Simple health-check endpoint used to verify that the plugin and service are available.

**Returns**
- Text confirmation message

---

### 2. `local_qbankremotemanager_upload_questions`
Uploads questions into the Question Bank of a given course.

**Parameters**
- `courseid` (int): Target course ID
- `itemid` (int): Draft file item ID containing a question XML file
- `questionbankid` (int): OPTIONAL on version 4

**Returns**
- Status
- Number of imported questions

---

### 3. `local_qbankremotemanager_upload_quiz`
Creates a quiz in a course, imports questions from an uploaded file, and adds them to the quiz.

**Parameters**
- `config` (object): Quiz configuration (name, timing, grading, visibility, completion, etc.)
- `itemid` (int): Draft file item ID containing a question XML file
- `questionbankid` (int): OPTIONAL on version 4

**Returns**
- Quiz course module ID
- Status
- Number of added questions

---

### 4. `local_qbankremotemanager_get_question_categories`
Returns all available question categories for a given course context.

**Parameters**
- `courseid` (int)
- `questionbankid` (int): OPTIONAL on version 4

**Returns**
- Course context ID
- List of categories (ID, title)

---

### 5. `local_qbankremotemanager_get_question_banks_for_course`
Returns all available questions banks for given course

**Parameters**
- `courseid` (int)

**Returns**
- List of questions banks (ID, title)

---

## File Upload Workflow

This plugin expects question files to be uploaded using Moodle’s **draft file area**:

1. Upload a question file (XML format) into the user draft area
2. Obtain the `itemid`
3. Call one of the provided web service functions with the `itemid`
4. The plugin processes and imports the file internally

---

## Permissions & Security

All web service functions:
- validate the course context,
- check required Moodle capabilities, including:
  - `moodle/question:add`
  - `moodle/question:editall`
  - `moodle/question:managecategory`
  - `mod/quiz:addinstance`
  - `mod/quiz:manage`

Only users with appropriate permissions can successfully call the API.

---

## Requirements

- Moodle **4.1 or newer**
- Question Bank Import plugin (`qbank_importquestions`) enabled
- Web Services enabled in Moodle
- An authentication method for web services (e.g. token-based)


---

## Use Cases

- Integration with external exam or content management systems
- Automated quiz creation
- Centralized question management
- Migration of questions from external tools into Moodle

---

## Limitations

- Only XML question format is currently supported
- Uploaded files must be provided via the user draft file area
- The plugin does not provide a user interface; it is API-only

---

## License

This plugin is licensed under the GNU GPL v3 or later.

---

## Author

Developed as a Moodle integration plugin for automated Question Bank and Quiz management.

---
## Academic Background

This plugin was originally developed as part of the author's Master's thesis at the Technical University of Košice (TUKE), Faculty of Electrical Engineering and Informatics, Department of Computers and Informatics (KPI).