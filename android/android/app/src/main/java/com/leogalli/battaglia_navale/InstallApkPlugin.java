package com.leogalli.battaglia_navale;

import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;
import androidx.core.content.FileProvider;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;

@CapacitorPlugin(name = "InstallApk")
public class InstallApkPlugin extends Plugin {

    private static final String APK_NAME = "battaglia_navale_update.apk";
    private long pendingDownloadId = -1L;
    private BroadcastReceiver downloadReceiver;

    @PluginMethod
    public void openReleasePage(PluginCall call) {
        String url = call.getString("url");
        if (url == null || url.isEmpty()) {
            call.reject("url mancante");
            return;
        }
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        getActivity().startActivity(intent);
        call.resolve();
    }

    @PluginMethod
    public void canInstallPackages(PluginCall call) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            boolean ok = getContext().getPackageManager().canRequestPackageInstalls();
            call.resolve(new com.getcapacitor.JSObject().put("allowed", ok));
            return;
        }
        call.resolve(new com.getcapacitor.JSObject().put("allowed", true));
    }

    @PluginMethod
    public void openInstallPermissionSettings(PluginCall call) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES);
            intent.setData(Uri.parse("package:" + getContext().getPackageName()));
            getActivity().startActivity(intent);
        }
        call.resolve();
    }

    @PluginMethod
    public void downloadAndInstall(PluginCall call) {
        String url = call.getString("url");
        if (url == null || url.isEmpty()) {
            call.reject("url mancante");
            return;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (!getContext().getPackageManager().canRequestPackageInstalls()) {
                call.reject("install_permission_required");
                return;
            }
        }

        unregisterReceiverSafe();
        DownloadManager dm = (DownloadManager) getContext().getSystemService(Context.DOWNLOAD_SERVICE);
        if (dm == null) {
            call.reject("DownloadManager non disponibile");
            return;
        }

        File dir = getContext().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
        if (dir != null && !dir.exists()) {
            dir.mkdirs();
        }
        final File target = new File(dir, APK_NAME);
        if (target.exists()) {
            target.delete();
        }

        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
        request.setTitle("Battaglia Navale");
        request.setDescription("Download aggiornamento");
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        request.setDestinationInExternalFilesDir(getContext(), Environment.DIRECTORY_DOWNLOADS, APK_NAME);

        pendingDownloadId = dm.enqueue(request);

        downloadReceiver =
            new BroadcastReceiver() {
                @Override
                public void onReceive(Context context, Intent intent) {
                    long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L);
                    if (id != pendingDownloadId) {
                        return;
                    }
                    Uri downloaded = resolveDownloadUri(dm, id);
                    if (downloaded == null) {
                        downloaded = Uri.fromFile(target);
                    }
                    promptInstall(downloaded, target);
                    unregisterReceiverSafe();
                }
            };

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getContext()
                .registerReceiver(
                    downloadReceiver,
                    new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
                    Context.RECEIVER_NOT_EXPORTED
                );
        } else {
            getContext()
                .registerReceiver(downloadReceiver, new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE));
        }

        call.resolve(new com.getcapacitor.JSObject().put("started", true));
    }

    private Uri resolveDownloadUri(DownloadManager dm, long id) {
        DownloadManager.Query query = new DownloadManager.Query().setFilterById(id);
        try (Cursor cursor = dm.query(query)) {
            if (cursor != null && cursor.moveToFirst()) {
                int status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                if (status == DownloadManager.STATUS_SUCCESSFUL) {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                        int uriIndex = cursor.getColumnIndex(DownloadManager.COLUMN_LOCAL_URI);
                        if (uriIndex >= 0) {
                            String s = cursor.getString(uriIndex);
                            if (s != null) {
                                return Uri.parse(s);
                            }
                        }
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private void promptInstall(Uri uri, File fallbackFile) {
        Context ctx = getContext();
        Uri contentUri = uri;
        if (contentUri == null || "file".equals(contentUri.getScheme())) {
            File file = fallbackFile;
            if (uri != null && "file".equals(uri.getScheme())) {
                file = new File(uri.getPath());
            }
            contentUri =
                FileProvider.getUriForFile(ctx, ctx.getPackageName() + ".fileprovider", file);
        }

        Intent install = new Intent(Intent.ACTION_VIEW);
        install.setDataAndType(contentUri, "application/vnd.android.package-archive");
        install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        install.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getActivity().startActivity(install);
    }

    private void unregisterReceiverSafe() {
        if (downloadReceiver != null) {
            try {
                getContext().unregisterReceiver(downloadReceiver);
            } catch (Exception ignored) {
            }
            downloadReceiver = null;
        }
    }

    @Override
    protected void handleOnDestroy() {
        unregisterReceiverSafe();
        super.handleOnDestroy();
    }
}
