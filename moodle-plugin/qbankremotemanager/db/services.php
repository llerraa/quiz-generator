<?php
// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <http://www.gnu.org/licenses/>.

/**
 * Function declarations and service definition for QBank Remote Manager plugin.
 * @package local_qbankremotemanager
 * @copyright 2026 Peter Vanát <vanat.peter@gmail.com>
 * @license http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

$functions = [
    'local_qbankremotemanager_am_i_here' => [
        'classname'    => 'local_qbankremotemanager\external\qbankremotemanager_external',
        'methodname'   => 'am_i_here',
        'description'  => 'Tests if this plugin is available in LMS Moodle instance.',
        'type'         => 'read',
        'ajax'         => true,
    ],
    'local_qbankremotemanager_upload_quiz' => [
        'classname'    => 'local_qbankremotemanager\external\qbankremotemanager_external',
        'methodname'   => 'upload_quiz',
        'description'  => 'Uploads new quiz to course with questions from file in
                           Moodle XML format. This file must be uploaded beforehand.',
        'type'         => 'write',
        'ajax'         => true,
    ],
    'local_qbankremotemanager_get_question_categories' => [
        'classname'    => 'local_qbankremotemanager\external\qbankremotemanager_external',
        'methodname'   => 'get_question_bank_categories',
        'description'  => 'Retrieve categories available for export from question bank.',
        'type'         => 'read',
        'ajax'         => true,
    ],
    'local_qbankremotemanager_upload_questions' => [
        'classname'    => 'local_qbankremotemanager\external\qbankremotemanager_external',
        'methodname'   => 'upload_questions',
        'description'  => 'Import new questions to questions bank from Moodle XML format. This file must be uploaded beforehand.',
        'type'         => 'write',
        'ajax'         => true,
    ],
    'local_qbankremotemanager_get_question_banks_for_course' => [
        'classname'    => 'local_qbankremotemanager\external\qbankremotemanager_external',
        'methodname'   => 'get_question_banks_for_course',
        'description'  => 'Retrieves all question banks available in given course.',
        'type'         => 'read',
        'ajax'         => true,
    ],
];

$services = [
    'QBank Remote Manager API' => [
        'functions' => [
            'local_qbankremotemanager_upload_quiz',
            'local_qbankremotemanager_am_i_here',
            'local_qbankremotemanager_get_question_categories',
            'local_qbankremotemanager_upload_questions',
            'local_qbankremotemanager_get_question_banks_for_course',
        ],
        'restrictedusers' => 0,
        'enabled'         => 1,
        'shortname'       => 'qbank_manager',
    ],
];
