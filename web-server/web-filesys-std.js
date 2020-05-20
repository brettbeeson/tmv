import './bbutils.js'
/**
 * Access the server filesystem via apache-style directory listings (HTML)
 */

import  { baseName, splitPath, bytesToHumanReadable } from "./bbutils.js";

export class WebFileSysStd {

    constructor() {
        this.IMG_EXTENSIONS = ['bmp', 'gif', 'jpg', 'jpeg', 'jpe', 'png'];
        this.VIDEO_EXTENSIONS = ['mp4', 'mov', 'avi'];
        this.MISC_ELEMENTS = [];
        this.IGNORED_ELEMENTS = ['..', 'Name', 'Last modified', 'Size', 'Description', 'Parent Directory'];
    }

    /**
     * Given a directory, return a list of files (eg file.txt) and directories (eg. directory/)
     * dirname starts at bucket root
     * @returns array of files and directories in dirname, relative to dirname
     */
    ls(dirname) {
        let dir_entries = [];
        dirname = dirname.slashEnd(true);

        let request = $.ajax({
            url: dirname,
            method: "GET",
            dataType: "html",
            async: false,
            error: function (xhr, status, error) {

                console.log(xhr.responseText + "," + status + "," + error);
            }
        });
        request.done(function (html) {
            let page_title = $(html).filter("title").text();
            if (page_title.search(/directory listing/i) !== -1) {
                $(html).find("a").each(function (i, element) {
                    dir_entries.push(element.getAttribute('href'));
                    //console.log("Got: " + element.getAttribute('href'));
                })
            } else {
                console.log("No directory available for " + dirname);
            }
        });
        return dir_entries;
    }

    fileExists(url) {
        let http = new XMLHttpRequest();
        http.open('HEAD', url, false);
        http.send();
        return http.status !== 404;
    }


    isImage(path) {
        return $.inArray(path.split('.').pop().toLowerCase(), this.IMG_EXTENSIONS) !== -1;
    }

    isVideo(path) {
        return $.inArray(path.split('.').pop().toLowerCase(), this.VIDEO_EXTENSIONS) !== -1;
    }

    static isDir(path) {
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
     * eg some/dir/movie/movie.mpd
     * dashDir("some/dir/movie") = True
     * @param path
     * @returns {boolean}
     */
    isDashDir(path) {
        if (!this.isDir(path)) {
            return false;
        }
        let dir_files = this.ls(path);
        let mpd_entries = dir_files.filter(function (d) {
            return /.*.mpd$/.test(d);
        });
        let dir_entries = dir_files.filter(function (d) {
            return isDir(d);
        });
        return mpd_entries.length === 1 && dir_entries.length === 0;
    }

    /**
     * A Dash Dir contains ONE .mpd file and ZERO folders
     * @returns string fileame of file matching *.mpd
     */
    dashFile(path) {
        let dirfiles = fs.ls(path);
        let mpd_entries = dirfiles.filter(function (d) {
            return /.*.mpd$/.test(d);
        });
        if (mpd_entries.length > 0) {
            return path.slashEnd(true) + mpd_entries[0];
        } else {
            return "";
        }
    }

    /**
     * Adds the webroot (whatever is required at the start) to a resource location
     * eg urlTo('foo/bar.txt') => http://server.com/moose/foo/bar.txt
     * @param resource file or directory relative to webroot
     */
    urlTo(resource) {
        return resource;
    }
}
