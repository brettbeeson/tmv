/**
 * Access an S3 filesystem via S3 REST API (xml)
 */

import  { baseName, splitPath, bytesToHumanReadable } from "./bbutils.js";

export class WebFileSysS3 {

    constructor(_BUCKET_URL) {
        // Axiom: ends in slash
        this.BUCKET_URL = _BUCKET_URL.slashEnd(true);
        this.IMG_EXTENSIONS = ['bmp', 'gif', 'jpg', 'jpeg', 'jpe', 'png'];
        this.VIDEO_EXTENSIONS = ['mp4', 'mov', 'avi'];
        this.MISC_ELEMENTS = [];
        this.IGNORED_ELEMENTS = [];
    }

    //private
    createS3QueryUrl(prefix) {

        let s3_rest_url = this.BUCKET_URL;
        s3_rest_url += '?delimiter=/';
        //let rx = '.*[?&]prefix=' + this.S3B_ROOT_DIR + '([^&]+)(&.*)?$';
        //let match = location.search.match(rx);
        //if (match) {
//            prefix = this.S3B_ROOT_DIR + match[1];
  //      } else {
    //        if (this.S3BL_IGNORE_PATH) {
      //          prefix = this.S3B_ROOT_DIR;
        //    }
        //}
        if (prefix && prefix !== '' && prefix !== "/") {
            // make sure we end in / for directories
            // root shouldn't have a prefix (prefix="/" fails)
            s3_rest_url += '&prefix=' + prefix;
        }
        //if (marker) {
//            s3_rest_url += '&marker=' + marker;
//        }
        return s3_rest_url;
    };

    // private
    getInfoFromS3Data(xml) {
        let files = $.map(xml.find('Contents'), function (item) {
            item = $(item);
            // clang-format off
            return {
                Key: item.find('Key').text(),
                LastModified: item.find('LastModified').text(),
                Size: bytesToHumanReadable(item.find('Size').text()),
                Type: 'file'
            }
            // clang-format on
        });
        let directories = $.map(xml.find('CommonPrefixes'), function (item) {
            item = $(item);
            // clang-format off
            return {
                Key: item.find('Prefix').text(),
                LastModified: '',
                Size: '0',
                Type: 'directory'
            }
            // clang-format on
        });
        let nextMarker;
        if ($(xml.find('IsTruncated')[0]).text() === 'true') {
            nextMarker = $(xml.find('NextMarker')[0]).text();
        } else {
            nextMarker = null;
        }
        // clang-format off
        return {
            files: files,
            directories: directories,
            prefix: $(xml.find('Prefix')[0]).text(),
            nextMarker: encodeURIComponent(nextMarker)
        }
    }


    /**
     * Given a directory, return a list of files (eg file.txt) and directories (eg. directory/)
     * dirname starts at bucket root
     * @returns array of files and directories in dirname, relative to dirname
     */
    ls(dirname) {
        dirname = dirname.slashEnd(true);
        let dir_entries = [];
        let s3_rest_url;
        s3_rest_url = this.createS3QueryUrl(dirname);

        let request = $.ajax({
            url: s3_rest_url,
            method: "GET",
            dataType: "html",
            async: false,
            error: function (xhr, status, error) {
                console.log(xhr.responseText + "," + status + "," + error);
            }
        });
        request.done((data) => {
            let xml = $(data);
            let info = this.getInfoFromS3Data(xml);
            // info: {Key: "index.html", LastModified: "2019-10-09T12:52:31.000Z", Size: "4.5 kB", Type: "file"}
            // console.log(info);
            info.files.forEach((e) => {
                // s3 gives back foo/bar.txt
                // we need just bar.txt
                let p = splitPath(e.Key);
                if ((p['filename'] + p['extension']).length>0) {
                    dir_entries.push(p['filename'] + p['extension']);
                }
            });

            info.directories.forEach(function (e) {
                // s3 gives back foo/bar/
                // we need just bar/
                dir_entries.push(baseName(e.Key.slashEnd(false)) + "/");
            });
        });
        return dir_entries;
    }

    /**
     * File or directory exists
     * @param filename
     * @returns {boolean}
     */
    fileOrDirExists(itemname) {
        itemname = itemname.slashStart(false).slashEnd(false);
        let exists = false;
        let s3_rest_url;
        s3_rest_url = this.createS3QueryUrl(itemname);

        let request = $.ajax({
            url: s3_rest_url,
            method: "GET",
            dataType: "html",
            async: false,
            error: function (xhr, status, error) {
                console.log(xhr.responseText + "," + status + "," + error);
            }
        });
        request.done( (data) => {
            let xml = $(data);
            let info = this.getInfoFromS3Data(xml);
            exists = (info.files.length>0) || (info.directories.length>0)
        });
        return exists;
    }



    fileExists(filename) {
        filename = filename.slashStart(false);  // s3 cannot have "/" at start
        let exists = false;
        let s3_rest_url;
        s3_rest_url = this.createS3QueryUrl(filename);

        let request = $.ajax({
            url: s3_rest_url,
            method: "GET",
            dataType: "html",
            async: false,
            error: function (xhr, status, error) {
                console.log(xhr.responseText + "," + status + "," + error);
            }
        });
        request.done( (data) => {
            let xml = $(data);
            let info = this.getInfoFromS3Data(xml);
            exists = (info.files.length>0);
        });
        return exists;
    }

    dirExists(dirname) {
        dirname = dirname.slashEnd(true); // s3 returns directories with slashes at end
        let exists = false;
        let s3_rest_url;
        s3_rest_url = this.createS3QueryUrl(dirname);
        let request = $.ajax({
            url: s3_rest_url,
            method: "GET",
            dataType: "html",
            async: false,
            error: function (xhr, status, error) {
                console.log(xhr.responseText + "," + status + "," + error);
            }
        });
        request.done( (data) => {
            let xml = $(data);
            let info = this.getInfoFromS3Data(xml);
            exists = (info.directories.length > 0);
        });
        return exists;
    }

    isImage(path) {
        return $.inArray(path.split('.').pop().toLowerCase(), this.IMG_EXTENSIONS) !== -1;
    }

    isVideo(path) {
        return $.inArray(path.split('.').pop().toLowerCase(), this.VIDEO_EXTENSIONS) !== -1;
    }

    isDir(path) {
        return path.slice(-1) === "/";
    }

    isMisc(path) {
        return $.inArray(path.split('.').pop().toLowerCase(), this.MISC_ELEMENTS) !== -1;
    }

    isIgnored(path) {
        return $.inArray(path, this.IGNORED_ELEMENTS) !== -1;
    }

    /**
     * A Dash Dir contains ONE .mpd file and ZERO folders
     * @returns {string} filename of first file matching *.mpd, or ""
     */
    dashFile(path) {
        let dir_files = this.ls(path);
        let mpd_entries = dir_files.filter(function (d) {
            return /.*.mpd$/.test(d);
        });
        if (mpd_entries.length > 0) {
            return path.slashEnd(true) + mpd_entries[0];
        } else {
            return "";
        }
    }


    /**
     * A Dash Dir contains ONE .mpd file and ZERO folders
     * eg some/dir/movie/movie.mpd
     * dashDir("some/dir/movie") = True
     * @param path
     * @returns {boolean}
     */
    isDashDir(path) {
        if (!this.isDir(path)) {
            //return false;
        }
        let dir_files = this.ls(path);
        let mpd_entries = dir_files.filter( (d)=> {
            return /.*.mpd$/.test(d);
        });
        let dir_entries = dir_files.filter( (d)=> {
            return this.isDir(d);
        });
        return mpd_entries.length === 1 && dir_entries.length === 0;
    }

    /**
     * Adds the webroot (whatever is required at the start) to a resource location
     * eg urlTo('foo/bar.txt') => http://somebuck.aws.com/foo/bar.txt
     * @param resource file or directory relative to webroot
     */
    urlTo(resource) {
        return this.BUCKET_URL + resource.slashStart(false);
    }
}

// https://tc39.github.io/ecma262/#sec-array.prototype.includes
if (!Array.prototype.includes) {
    Object.defineProperty(Array.prototype, 'includes', {
        value: function (searchElement, fromIndex) {

            if (this == null) {
                throw new TypeError('"this" is null or not defined');
            }

            // 1. var O be ? ToObject(this value).
            var o = Object(this);

            // 2. var len be ? ToLength(? Get(O, "length")).
            var len = o.length >>> 0;

            // 3. If len is 0, return false.
            if (len === 0) {
                return false;
            }

            // 4. var n be ? ToInteger(fromIndex).
            //    (If fromIndex is undefined, this step produces the value 0.)
            var n = fromIndex | 0;

            // 5. If n ≥ 0, then
            //  a. var k be n.
            // 6. Else n < 0,
            //  a. var k be len + n.
            //  b. If k < 0, var k be 0.
            var k = Math.max(n >= 0 ? n : len - Math.abs(n), 0);

            function sameValueZero(x, y) {
                return x === y || (typeof x === 'number' && typeof y === 'number' && isNaN(x) && isNaN(y));
            }

            // 7. Repeat, while k < len
            while (k < len) {
                // a. var elementK be the result of ? Get(O, ! ToString(k)).
                // b. If SameValueZero(searchElement, elementK) is true, return true.
                if (sameValueZero(o[k], searchElement)) {
                    return true;
                }
                // c. Increase k by 1.
                k++;
            }

            // 8. Return false
            return false;
        }
    });
}

// This will sort your file listing by most recently modified.
// Flip the comparator to '>' if you want oldest files first.
function sortFunction(a, b, sort_order) {
    switch (sort_order) {
        case "OLD2NEW":
            return a.LastModified > b.LastModified ? 1 : -1;
        case "NEW2OLD":
            return a.LastModified < b.LastModified ? 1 : -1;
        case "A2Z":
            return a.Key < b.Key ? 1 : -1;
        case "Z2A":
            return a.Key > b.Key ? 1 : -1;
        case "BIG2SMALL":
            return a.Size < b.Size ? 1 : -1;
        case "SMALL2BIG":
            return a.Size > b.Size ? 1 : -1;
    }
}
