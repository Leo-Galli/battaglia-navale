package com.leogalli.battaglia_navale;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(InstallApkPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
