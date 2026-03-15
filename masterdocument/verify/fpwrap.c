// fpwrap_working.c — versi yang terbukti jalan
// Compile: bash build.sh
// Kunci: langsung pass raw bytes ke fp_print_deserialize tanpa parsing FP3

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <libfprint-2/fprint.h>
#include <glib.h>

static unsigned char *read_file(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz <= 0) { fclose(f); return NULL; }
    unsigned char *buf = malloc((size_t)sz);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) { free(buf); fclose(f); return NULL; }
    fclose(f);
    *out_len = (size_t)sz;
    return buf;
}

static FpPrint *load_print_file(const char *path) {
    size_t         len = 0;
    unsigned char *buf = read_file(path, &len);
    if (!buf || len == 0) return NULL;

    GError  *err   = NULL;
    FpPrint *print = NULL;

    // Langsung pass raw bytes — libfprint handle FP3 natively
    print = fp_print_deserialize((const guchar*)buf, (gsize)len, &err);
    if (err) { g_error_free(err); err = NULL; print = NULL; }

    free(buf);
    return print;
}

static void collect_prints(const char *dirpath, int depth,
                            GPtrArray *prints, GArray *paths) {
    if (depth > 5) return;

    DIR *d = opendir(dirpath);
    if (!d) {
        FpPrint *pr = load_print_file(dirpath);
        if (pr) {
            g_ptr_array_add(prints, pr);
            char *s = strdup(dirpath);
            g_array_append_val(paths, s);
            fprintf(stderr, "[fpwrap] loaded: %s\n", dirpath);
        }
        return;
    }

    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        char sub[1024];
        snprintf(sub, sizeof(sub), "%s/%s", dirpath, e->d_name);

        DIR *test = opendir(sub);
        if (test) {
            closedir(test);
            collect_prints(sub, depth + 1, prints, paths);
        } else {
            FpPrint *pr = load_print_file(sub);
            if (pr) {
                g_ptr_array_add(prints, pr);
                char *s = strdup(sub);
                g_array_append_val(paths, s);
                fprintf(stderr, "[fpwrap] loaded: %s\n", sub);
            }
        }
    }
    closedir(d);
}

int fpwrap_identify_from_dir(const char *dir_path,
                              char       *matched_filename,
                              int         matched_filename_size) {
    if (matched_filename && matched_filename_size > 0) matched_filename[0] = '\0';

    FpContext  *ctx  = fp_context_new();
    GPtrArray  *devs = fp_context_get_devices(ctx);
    if (!devs || devs->len == 0) { g_object_unref(ctx); return -1; }

    FpDevice *dev = g_ptr_array_index(devs, 0);
    GError   *err = NULL;
    if (!fp_device_open_sync(dev, NULL, &err)) {
        if (err) g_error_free(err);
        g_object_unref(ctx);
        return -2;
    }

    GPtrArray *prints = g_ptr_array_new_with_free_func(g_object_unref);
    GArray    *paths  = g_array_new(FALSE, FALSE, sizeof(char*));

    collect_prints(dir_path, 0, prints, paths);
    fprintf(stderr, "[fpwrap] %u templates loaded\n", prints->len);

    if (prints->len == 0) {
        fp_device_close_sync(dev, NULL, NULL);
        g_object_unref(ctx);
        g_ptr_array_free(prints, TRUE);
        g_array_free(paths, TRUE);
        return -4;
    }

    FpPrint *matched = NULL;
    GError  *ierr    = NULL;
    fp_device_identify_sync(dev, prints, NULL, NULL, NULL, &matched, NULL, &ierr);
    fp_device_close_sync(dev, NULL, NULL);
    g_object_unref(ctx);
    if (ierr) { g_error_free(ierr); }

    int ret = 0;
    if (matched) {
        for (guint i = 0; i < prints->len; i++) {
            if (g_ptr_array_index(prints, i) == matched) {
                char *fname = g_array_index(paths, char*, i);
                if (matched_filename && matched_filename_size > 0) {
                    strncpy(matched_filename, fname, matched_filename_size - 1);
                    matched_filename[matched_filename_size - 1] = '\0';
                }
                fprintf(stderr, "[fpwrap] MATCH: %s\n", fname);
                ret = 1;
                break;
            }
        }
    }

    for (guint i = 0; i < paths->len; i++) free(g_array_index(paths, char*, i));
    g_ptr_array_free(prints, TRUE);
    g_array_free(paths, TRUE);
    return ret;
}

int fpwrap_enroll_to_file(const char *out_path) {
    (void)out_path;
    return -999;
}
