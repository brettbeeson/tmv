import {splitPath, baseName} from "./bbutils.js";
import {WebFileSysS3} from './web-filesys-s3.js';

'use strict';
// http://ferret:8000/?base=files/moose#files/moose/moosling
// serves base files
// where base = files/moose/
// base_dir is relative to origin (eg. http://ferret:8000), with a trailing slash
// current_dir is relative to origin (eg. http://ferret:8000), with a trailing slash
// eg /files/moose/cub
// serves /files/moose/cub
// stored in URL's #

/**
 ***********************************************************************************
 * Globals
 ***********************************************************************************
 */
let base_dir = "";
let current_dir = "";
const TMV_BUCKET = "tmv.brettbeeson.com.au";
const TMV_BUCKET_URL = "http://" + TMV_BUCKET + ".s3-ap-southeast-2.amazonaws.com/";

const DATETIME_FORMAT = 'YYYY-MM-DDTHH-mm-ss';
const DATE_FORMAT = 'YYYY-MM-DD';
const TIME_FORMAT = 'HH-mm-ss';
const HOUR_FORMAT = 'HH-';
const FILE_PREFIX = "tl-alex-";

// Allow remote testing
//const host = "http://tmv.brettbeeson.com.au.s3-ap-southeast-2.amazonaws.com/";
// Normal Mode
//const host = '';

// Initialize the Amazon Cognito credentials provider
AWS.config.region = 'ap-southeast-2'; // Region
AWS.config.credentials = new AWS.CognitoIdentityCredentials({
    IdentityPoolId: 'ap-southeast-2:db4f53b6-3e51-4993-9fe6-f08924a57d75',
});

// Create a new service object
let s3 = new AWS.S3({
    apiVersion: '2006-03-01',
    params: {Bucket: TMV_BUCKET}
});

let fs = new WebFileSysS3(TMV_BUCKET_URL);

/**
 ***********************************************************************************
 * Functions
 ***********************************************************************************
 */

// https://stackoverflow.com/questions/26246601/wildcard-string-comparison-in-javascript
function wildcard_match(str, rule) {
    var escapeRegex = (str) => str.replace(/([.*+?^=!:${}()|\[\]\/\\])/g, "\\$1");
    return new RegExp("^" + rule.split("*").map(escapeRegex).join(".*") + "$").test(str);
  }
  
 
$(document).ajaxError(function (event, request, settings) {
    // debugging
    console.log("Ajax Error: " + settings.url + "," + request.status + "," + request.statusText);
});

function disable_button(button) {
    button.addClass('disabled');
    button.removeClass('active');
}

function unhide_element(element) {
    $(element).addClass("d-block");
    $(element).removeClass("d-none");
}

function hide_element(element) {
    element.addClass("d-none");
    element.removeClass("d-block");
}

function reset_elements(element) {
    hide_element($('#image-shower-div'));
    hide_element($('#video-player-div'));
    $('.list-group-item').not(element).removeClass('active');
    $('.list-group-item').removeClass('disabled');

}

/**
 * @todo Could cache
 * In prefix (not recursive)
 * @param bucket
 * @param prefix
 * @param recursive
 */
async function s3_objects(bucket, prefix, recursive = false, exclude = "*nfiles") {
    let isTruncated = true;
    let continuationToken;
    let objects = [];
    while (isTruncated) {
        let params = {Bucket: bucket};
        if (prefix) params.Prefix = prefix;
        if (continuationToken) params.ContinuationToken = continuationToken;
        if (!recursive) params.Delimiter = "/";
        try {
            const response = await s3.listObjectsV2(params).promise();
            response.Contents.forEach(item => {
                if (! wildcard_match(item.Key,exclude)) {
                    objects.push(item.Key);
                }
            });
            isTruncated = response.IsTruncated;
            if (isTruncated) {
                continuationToken = response.NextContinuationToken;
            }
        } catch (error) {
            throw error;
        }
    }
    return objects;
}

/**
 * @todo Could cache
 * @param bucket
 * @param prefix
 * @param recursive
 * @returns {Promise<Array>}
 */
async function s3_folders(bucket, prefix, recursive = false) {
    let isTruncated = true;
    let continuationToken;
    let objects = [];
    while (isTruncated) {
        let params = {Bucket: bucket};
        if (prefix) params.Prefix = prefix.slashEnd(true);
        if (continuationToken) params.ContinuationToken = continuationToken;
        if (!recursive) params.Delimiter = "/";
        try {
            const response = await s3.listObjectsV2(params).promise();
            response.CommonPrefixes.forEach(item => {
                objects.push(item.Prefix);

            });
            isTruncated = response.IsTruncated;
            if (isTruncated) {
                continuationToken = response.NextContinuationToken;
            }
        } catch (error) {
            throw error;
        }
    }
    return objects;
}

/**
 * Set via textbox or query string, this is the root for all references
 * @returns {boolean} Whether the URL contained "camera" to enable settings
 */
function set_base_dir_from_url() {
    // default: base if this html page's location relative to webroot
    //base_dir = location.pathname.replace('/index.html', '/').replace(/\/\//g, '/');
    base_dir = '';
    // add "base" setting via query string
    let searchParams = new URLSearchParams(window.location.search);
    if (searchParams.has('base')) {
        base_dir = decodeURIComponent(searchParams.get('base')).slashStart(false).slashEnd(true);
        if (base_dir.length > 1 && base_dir.search(".") !== -1) {
            $('#camera-selector').val(base_dir.slashEnd(false));
            return true;
        }
    }
    base_dir = '';
    return false;
}

/**
 * Open a file or disrectory at clickee's pathname/href
 * Use as onclick event handler
 * Uses 'title' for the resource location, which is based on webroot+prefix
 * Eg. Webroot: localhost/html/www/
 * => resource "bar.txt" looks for "localhost/html/www/bar.txt"
 * => adding "prefix="foo" looks for "localhost/html/www/foo/bar.txt"
 * Loads (i.e. set src) of non-existant resourses, but return false
 * @param event
 * @param prefix: add
 * @returns {boolean}
 */
function show_file_in_previewer_event(event, prefix = "") {
    if (!show_file_in_previewer(prefix + $(event.target).data("link"))) {
        disable_button($(event.target));
    }
}

function show_file_in_previewer(resource) {
    if (fs.isDashDir(resource)) {
        hide_element($("#image-shower-div"));
        showDashVideoInPreviewElement(resource);
    } else if (fs.isDir(resource)) {
        hide_element($("#video-player-div"));
        hide_element($("#image-shower-div"));
        cd(resource);
    } else if (fs.isImage(resource)) {
        hide_element($("#video-player-div"));
        showImageInPreviewElement(resource);
    } else if (fs.isVideo(resource)) {
        hide_element($("#image-shower-div"));
        showVideoInPreviewElement(resource);
    } else {
        alert("Unknown file type:" + resource);
        return false;
    }
    return fs.fileOrDirExists(resource);
}

/**
 *
 * @param href Link to resource.
 * @param name Name to display
 * @returns {HTMLAnchorElement}
 */
function createTile(link, name) {
    let a = document.createElement('a');
    //a.title = link;
    a.setAttribute("data-link", link);
    a.className = "list-group-item list-group-item-action";
    //a.target = "preview";
    a.innerText = name;
    a.addEventListener('click', show_file_in_previewer_event);
    return a;
}

// can replace
function createBackTile(title) {
    let a = document.createElement('a');
    a.setAttribute("data-link", splitPath(title.slashEnd((false)))['dirname']);
    a.className = "list-group-item list-group-item-action";
    a.innerText = "< Back";
    a.addEventListener('click', show_file_in_previewer_event);
    return a;
}

function isValidTile(path) {
    return !fs.isIgnored(path) && (fs.isDir(path) || fs.isMisc(path) || fs.isImage(path) || fs.isVideo(path));
}

// load the contents of the given directory
function cd(dir) {
    current_dir = decodeURIComponent(dir).slashStart(false).slashEnd(true);
    location.hash = current_dir;
    let path_elements = current_dir.slashEnd(false).split('/');
    $(".current-dir").empty();
    let temp_path = '';
    path_elements.forEach(function (pe) {
            if (pe.length > 0) {
                let a = document.createElement('a');
                temp_path += pe + '/';
                $(a).text(pe + '/');
                a.setAttribute("data-link", temp_path);
                a.href = "#";
                $(a).click((e) => {
                    e.preventDefault();
                    cd($(e.target).data("link"));
                    return false;
                });
                $(".current-dir").append(a);
            }
        }
    );

    $(".browser-view").empty();
    if (path_elements.length > 1) {
        $(".browser-view").append(createBackTile(current_dir));
    }

    let files_in_dir = fs.ls(current_dir);

    for (const file of files_in_dir) {
        if (isValidTile(current_dir + file)) {
            $(".browser-view").append(createTile(current_dir.slashEnd(true) + file, file));
        }
    }
}

function setImageCaption(filepath, suffix = '') {
    let date_readable = moment(baseName(filepath), "YYYY-MM-DDThh:mm:ss").format('LLLL');
    if (date_readable === "Invalid date") date_readable = baseName(filepath.slashEnd(false));
    $("#image-caption").text(date_readable + suffix);
    $("#image-caption").attr('title', filepath);
}

function showImageInPreviewElement(filepath) {
    setImageCaption(filepath);
    $("#image-shower-div").data("datetime", (moment(splitPath(filepath)['filename'], DATETIME_FORMAT).format(DATETIME_FORMAT)));
    $("#image-shower").attr("src", fs.urlTo(filepath));
    unhide_element("#image-shower-div");
}

function setVideoCaption(filepath) {
    let date_readable = moment(baseName(filepath.slashEnd(false)), "YYYY-MM-DD").format('LL');
    if (date_readable === "Invalid date") date_readable = baseName(filepath.slashEnd(false));
    $("#video-caption").text(date_readable);
    $("#video-caption").attr('title', filepath);
}

/**
 * Stream a video
 * @param filepath Directory with .mpd file. An mp4 file (of the *same name* as directory) will be used as fallback
 * Use DASH or fallback to plain mp4
 * Use video.js and dashjs.js to play video.
 */
function showDashVideoInPreviewElement(filepath) {
    let player = videojs('video-player');

    let sources = [];
    let mpd_file = fs.dashFile(filepath);
    if (mpd_file !== "") {
        sources.push({src: fs.urlTo(mpd_file), type: 'application/dash+xml'});
    }
    // Backup video for devices (eg Apple) which are crap.
    let mp4_file = filepath.slashEnd(false) + ".mp4";
    if (fs.fileExists(mp4_file)) {
        sources.push({src: fs.urlTo(mp4_file), type: 'video/mp4'});
    }
    player.src(sources);
    $("#video-player-div").data("date", (moment(splitPath(filepath.slashEnd(false))['filename'], DATE_FORMAT).format(DATE_FORMAT)));
    player.ready(() => {
        player.play();
    });
    unhide_element("#video-player-div");
    setVideoCaption(filepath);
}

/**
 *
 * @param filepath Filename (.mp4 required).
 */
function showVideoInPreviewElement(filepath) {

    let player = videojs('video-player');
    let sources = [];
    let mp4_file = filepath;
    if (fs.fileExists(mp4_file)) {
        sources.push({src: fs.urlTo(mp4_file), type: 'video/mp4'});
    }
    player.reset();
    player.src(sources);
    $("#video-player-div").data("date", (moment(splitPath(filepath)['filename'], DATE_FORMAT).format(DATE_FORMAT)));
    player.ready(() => {
        player.play();
    });
    unhide_element("#video-player-div");
    setVideoCaption(filepath);

}

function parentDir(path) {
    path = path.slashEnd(false);    // daily-video/2019-11-01.mp4
    let elements = path.split("/");       //daily-video,2019-11-01.mp4
    if (elements.length <= 2) return "";    //"/x".split("") =  ["/", "x"]
    elements.pop();
    return elements.join("/");
}

function show_rel_video(video, days) {
    let current_date =  $("#video-player-div").data("date");
    let new_video_basename = moment(current_date,DATE_FORMAT).add(days, 'days').format(DATE_FORMAT);
    /*
    let current_src = (new URL(video.currentSource().src) ).pathname;
    // Remove hostname:port will pass to showFileInPreview, which needs webroot relative path
    let splut = splitPath(current_src);
    let current_video_d = moment(splut['filename'], DATE_FORMAT);
    let new_video_d = current_video_d.clone().add(days, 'days');
    let new_video_basename = new_video_d.format(DATE_FORMAT);
    let new_video_dir;
    let new_video_src;

    // need to to handle mpd and mp4:
    if (splut['extension'] === '.mp4') {
        // daily-video/2019-11-01.mp4
        new_video_dir = parentDir(current_src).slashEnd(true);
    } else if (splut['extension'] === '.mpd') {
        // daily-video/2019-11-01/2019-11-01.mpd
        new_video_dir = parentDir(parentDir(current_src)).slashEnd(true);
    } else {
        // take a guess
        new_video_dir = base_dir + "daily-videos/";
    }

     */
    let new_video_dir = base_dir + "daily-videos/";
    let new_video_src;
    if (fs.isDashDir(new_video_dir + new_video_basename)) {
        new_video_src = new_video_dir + new_video_basename;
    } else {
        new_video_src = new_video_dir + new_video_basename + ".mp4";
    }

    let h = video.height();
    let w = video.width();
    if (!show_file_in_previewer(new_video_src)) {
        // If image is not available, show a blank of the previous size
        $(video).height(h);
        $(video).width(w);
    } else {
        // Reset responsive image
        $(video).css('height', 'auto');
        $(video).css('width', 'auto');
    }
}

function show_rel_image(image, minutes) {
    let current_datetime =   moment($('#image-shower-div').data("datetime"),DATETIME_FORMAT);
    let new_image_basename = current_datetime.clone().add(minutes, 'minutes').format(DATETIME_FORMAT);
    let new_image_dir =   current_datetime.format(DATE_FORMAT) + "/";
    let new_image_src = base_dir + "daily-photos/" + new_image_dir + new_image_basename + ".jpg";
    let h = image.height();
    let w = image.width();

    if (show_file_in_previewer(new_image_src)) {
        image.css('height', 'auto');
        image.css('width', 'auto');
    } else {
        image.height(h);
        image.width(w);
    }
}


jQuery(document).ready(function () {
        /**
         ***********************************************************************************
         * Attach events
         ***********************************************************************************
         */
        $('.rel-link').click(function (e) {
            if (base_dir !== "") {
                show_file_in_previewer_event(e, base_dir);
            }
        });

        $('.image-hours-ago').click(function (e) {
            hide_element($('#video-player-div'));
            let hours_ago = $(e.target).data('hours');
            if (base_dir === "" || !hours_ago) return;
            let image_datetime = moment().subtract(hours_ago, "hours").clone();
            let search_date = image_datetime.format(DATE_FORMAT);
            let search_hour = image_datetime.format(HOUR_FORMAT);
            (async () => {
                let prefix = base_dir + "daily-photos/" + search_date + "/" +
                    FILE_PREFIX + search_date + "T" + search_hour;
                let photos_that_hour = await s3_objects(TMV_BUCKET, prefix, false);
                if (photos_that_hour.length > 0) {
                    showImageInPreviewElement(photos_that_hour[0]);
                } else {
                    disable_button($(e.target));
                    console.log("No photos found");
                }
            })();
        });

        $('#latest-image').click(function (e) {
            let latest_photo;
            hide_element($('#video-player-div'));
            if (base_dir === "") return;
            // Run backwards through the days, get the last
            // Do this async and await the s3 results sequentially
            (async () => {
                let dates_with_photos = await s3_folders(TMV_BUCKET, base_dir + "daily-photos/", false);
                for (let d of dates_with_photos.reverse()) {
                    let photos = await s3_objects(TMV_BUCKET, d, false);
                    if (photos.length > 0) {
                        latest_photo = photos[photos.length - 1];
                        showImageInPreviewElement(latest_photo);
                        return false;
                    }
                }
                console.log("#latest-image found no images");
            })();
        });

        $('#latest-video').click(function (e) {
            e.preventDefault();
            hide_element($('#image-shower-div'));
            if (base_dir === "") return;
            (async () => {
                let videos_mp4 = await s3_objects(TMV_BUCKET, base_dir + "daily-videos/", false);
                let videos_dash = await s3_folders(TMV_BUCKET, base_dir + "daily-videos/", false);
                if (videos_dash.length > 0 && videos_mp4.length > 0) {
                    // choose the latest. Looks at start time - probably ok.
                    // eg.  "2019-10-16T04_to_2019-10-16T13" >= "2019-10-16T04_to_2019-10-16T12"
                    if (baseName(videos_dash[videos_dash.length - 1].slashEnd(false)) >=
                        baseName(videos_mp4[videos_mp4.length - 1])) {
                        showDashVideoInPreviewElement(videos_dash[videos_dash.length - 1]);
                    } else {
                        showVideoInPreviewElement(videos_mp4[videos_mp4.length - 1])
                    }
                } else if (videos_dash.length > 0) {
                    // only dash available
                    showDashVideoInPreviewElement(videos_dash[videos_dash.length - 1]);
                } else if (videos_mp4.length > 0) {
                    // only mp4 available
                    showVideoInPreviewElement(videos_mp4[videos_mp4.length - 1])
                } else {
                    console.log("#latest-video found no video");
                }

            })();
        });

        $(".nav-image-hours").click((e) => show_rel_image($("#image-shower"), $(e.target).data("hours") * 60));
        $(".nav-image-minutes").click((e) => show_rel_image($("#image-shower"), $(e.target).data("minutes")));
        // video.js changes <video> name, so find it as child of div
        $(".nav-video-days").click((e) => show_rel_video(videojs('video-player'), $(e.target).data("days")));

        $('#refresh').click(function () {
            reset_elements();
            cd(current_dir);
        });

        $("#camera-select").click(function (e) {
            e.preventDefault();
            // Note conversion to lowercase. Mobile devices use Titlecase as default
            let camera_field = $('#camera-selector');
            camera_field.val(camera_field.val().toLowerCase());
            let new_base = camera_field.val().slashEnd(true);
            if (new_base.length <= 1 || fs.ls(new_base).length === 0) {
                $("#camera-invalid").addClass("d-block");
                base_dir = "";
                $(".current-dir").empty();
                $(".browser-view").empty();
            } else {
                $("#camera-invalid").removeClass("d-block");
                if ('URLSearchParams' in window) {
                    let searchParams = new URLSearchParams(window.location.search);
                    searchParams.set("base", encodeURIComponent(new_base.slashEnd(false)));
                    let newRelativePathQuery = window.location.pathname + '?' + searchParams.toString();
                    history.pushState(null, '', newRelativePathQuery);
                } else {
                    console.log("URLSearchParams not available");
                }
                base_dir = new_base.slashEnd(true); // global
                cd(base_dir);
                $('#latest-image').trigger("click");
            }
            return false;
        });

        /**
         ***********************************************************************************
         * Main
         ***********************************************************************************
         */
        let current_dir = (location.hash.substring(1) + '/').replace(/\/\//g, '/').slashStart(false).slashEnd(true);
        if (current_dir.includes("..")) {
            current_dir = '';
        }
        if (set_base_dir_from_url()) {
            cd(base_dir);
            $('#latest-image').trigger("click");
        } else {
            // $("#camera-selector").effect("shake", "distance");
        }

        if (window.jQuery().datetimepicker) {
            $('.datetimepicker1').datetimepicker({
                // Formats
                // follow MomentJS docs: https://momentjs.com/docs/#/displaying/format/
                format: 'DD-MM-YYYY hh:mm A',

                // Your Icons
                // as Bootstrap 4 is not using Glyphicons anymore
                icons: {
                    time: 'fa fa-clock-o',
                    date: 'fa fa-calendar',
                    up: 'fa fa-chevron-up',
                    down: 'fa fa-chevron-down',
                    previous: 'fa fa-chevron-left',
                    next: 'fa fa-chevron-right',
                    today: 'fa fa-check',
                    clear: 'fa fa-trash',
                    close: 'fa fa-times'
                }
            });
        }
    }
);