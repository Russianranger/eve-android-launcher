package io.github.russianranger.eve;

import android.view.View;

/** Display pixels and input share a contract while each presentation path owns its lifecycle. */
interface RfbScreen extends RfbClient.Screen {
    View view();
    void setPointer(RfbView.Pointer value);
    void setPerformance(DisplayPerformance value);
    void resumePresentation();
    void pausePresentation();
    void releasePointer();
    void dispose();
}
